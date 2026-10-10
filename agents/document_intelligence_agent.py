"""
Document Intelligence Agent for OmniDoc.

Layout-aware context, without model calls:

* follows explicit references in the question ("Table 3", "Figure 2", "section 4.1",
  "page 12", "pages 16 and 18", "page(1)", "page nine", "the last page", "the cover page",
  "clause 7", "slide 5") to the passages that contain them, even when the search did not
  rank them;
* adds the financial statements a question names ("statement of financial position") or
  needs for the figures it asks about (inventory, COGS, capex...), recognised by their line
  items and amounts: the text search rarely ranks a page of numbers first;
* adds the neighbouring passage when a top passage stops mid-sentence or starts in the
  middle of one, so the writer sees the whole statement.

Added passages carry the relevance of the passage they belong to and are marked
``layout_context`` or ``reference``.
"""
import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.state import AgentWorkflowState
from agents.llm_utils import trace

logger = logging.getLogger("OmniDoc.DocumentIntelligence")

_REF = re.compile(r"\b(table|figure|fig\.?|section|chapter|appendix|annex|exhibit|schedule|clause|article|slide|page|p\.)\s*"
                  r"([0-9]+(?:\.[0-9]+)*[a-z]?|[A-Z](?![a-z]))", re.I)
_KIND_PATTERN = {"fig": r"fig(?:ure|\.)?", "figure": r"fig(?:ure|\.)?", "p.": r"page", "page": r"page"}
_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
_ORDINALS = {w: i for i, w in enumerate(
    "zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth".split())}
_NUM = r"(\d{1,4}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + ")"
# "page 12", "pages 16 and 18", "pages 3-5", "page(1)", "slide nine", "p. 4"
_PAGE_LIST = re.compile(r"\b(?:pages?|slides?|p\.)\s*\(?\s*" + _NUM + r"\s*\)?((?:\s*(?:,|and|&|to|-|–)\s*" + _NUM + r")*)", re.I)
# "the last page", "the cover page", "the third slide"
_PAGE_WORD = re.compile(r"\b(last|final|cover|front|title|" + "|".join(_ORDINALS) + r")\s+(?:page|slide)\b", re.I)
MAX_DOCS = 3
TOP_PASSAGES = 3
# Financial statements: (what in a question calls for it, how its heading reads in a filing,
# the line items it is made of). Headings are often lost to the layout ("(In thousands)"),
# so a statement is recognised by its line items and its density of amounts.
_STATEMENTS = (
    (re.compile(r"balance sheets?|financial (position|condition)|working capital|current (assets|liabilities|ratio)|quick ratio|"
                r"inventor(y|ies)|receivables?|payables?|total (assets|liabilities|debt)|(shareholders|stockholders)'? equity|"
                r"PP&E|property,? plant|book value|days (payable|sales|inventory)", re.I),
     re.compile(r"balance sheets?|statements? of (consolidated )?financial (position|condition)", re.I),
     re.compile(r"total current assets|total assets|total current liabilities|total liabilities|(stockholders|shareholders)['’]? equity|"
                r"retained earnings|accounts payable|inventories|property(, plant)? and equipment|cash and cash equivalents", re.I)),
    (re.compile(r"income statements?|statements? of (consolidated )?(income|operations|earnings)|profit (and|&) loss|\bP&L\b|"
                r"revenues?|net sales|COGS|cost of (goods sold|sales|revenues?)|gross (profit|margin)|operating (income|margin|profit)|"
                r"net (income|earnings|margin|loss)|EBIT(DA)?|earnings per share|\bEPS\b|interest expense|turnover|return on", re.I),
     re.compile(r"statements? of (consolidated )?(income|operations|earnings|comprehensive income)|income statements?|profit (and|&) loss", re.I),
     re.compile(r"net sales|total (net )?revenues?|cost of (sales|revenues?|goods sold)|gross (profit|margin)|operating (income|profit)|"
                r"income before income taxes|provision for income taxes|net (income|earnings)|per (common )?share|diluted", re.I)),
    (re.compile(r"cash ?flows?|capex|capital expenditures?|purchases? of property|dividends? paid|share repurchases?|"
                r"(operating|investing|financing) activities", re.I),
     re.compile(r"statements? of (consolidated )?cash flows?|cash flows? statements?", re.I),
     re.compile(r"operating activities|investing activities|financing activities|net cash (provided|used)|"
                r"depreciation and amortization|capital expenditures|purchases? of property|dividends paid|end of (the )?(year|period)", re.I)),
)
STATEMENT_PASSAGES = 2   # per statement: the best block and the passage next to it
MAX_STATEMENT_PASSAGES = 5
STATEMENT_MIN_AMOUNTS = 6  # a statement is full of amounts (44,538 / 3.46); a contents page has page numbers
_AMOUNT = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+")


def _number(token: str) -> Optional[int]:
    token = token.lower()
    return int(token) if token.isdigit() else _NUMBER_WORDS.get(token)


def page_references(query: str) -> List[str]:
    """Pages the question names, as numbers in text ("12") or "last"; at most six."""
    out: List[str] = []
    for m in _PAGE_LIST.finditer(query or ""):
        first = _number(m.group(1))
        nums = [first] + [_number(t) for t in re.findall(_NUM, m.group(2) or "", re.I)]
        if re.search(r"\d\s*(?:to|-|–)\s*\d", m.group(0)) and len(nums) == 2 and None not in nums and 0 < nums[1] - nums[0] <= 5:
            nums = list(range(nums[0], nums[1] + 1))  # a short range: pages 3-5
        out += [str(n) for n in nums if n]
    for m in _PAGE_WORD.finditer(query or ""):
        word = m.group(1).lower()
        out.append("last" if word in ("last", "final") else "1" if word in ("cover", "front", "title") else str(_ORDINALS[word]))
    return list(dict.fromkeys(out))[:6]


def _real(ch: Dict[str, Any]) -> bool:
    return isinstance(ch, dict) and bool(ch.get("chunk_id")) and bool(ch.get("text"))


class DocumentIntelligenceAgent:
    """Follows document references and adds neighbouring passages around the best hits."""

    def __init__(self, lance_store: Any = None):
        self.lance_store = lance_store

    def _chunks(self, doc_id: str, cache: Dict[str, List[Any]]) -> List[Any]:
        if doc_id not in cache:
            try:
                cache[doc_id] = self.lance_store.get_document_chunks(doc_id) if self.lance_store else []
            except Exception as e:
                logger.warning(f"Could not read chunks of {doc_id}: {e}")
                cache[doc_id] = []
        return cache[doc_id]

    @staticmethod
    def references(query: str) -> List[Tuple[str, str]]:
        """References in the question: ("table", "3"), ("figure", "2"), ("page", "12"), ("page", "last"), ..."""
        out = [("page", n) for n in page_references(query)]
        for kind, num in _REF.findall(query or ""):
            kind = kind.lower().rstrip(".") if kind.lower() != "p." else "page"
            if kind in ("page", "slide"):
                continue  # read above, with lists, words and "the last page"
            if (kind, num) not in out:
                out.append((kind, num))
        return out[:6]

    def _reference_hits(self, kind: str, num: str, chunks: List[Any]) -> List[Any]:
        if kind == "page":
            if num == "last":
                num = str(max((c.page_number for c in chunks), default=0))
            return [c for c in chunks if str(c.page_number) == num][:2]
        word = _KIND_PATTERN.get(kind, re.escape(kind))
        pattern = re.compile(rf"\b{word}\s*{re.escape(num)}\b", re.I)
        # A caption ("Table 3: ...", "Figure 2. ...") beats a passing mention.
        caption = re.compile(rf"(^|\n|\.\s)\s*{word}\s*{re.escape(num)}\s*[:.\-–]", re.I)
        hits = [c for c in chunks if pattern.search(c.text)]
        hits.sort(key=lambda c: 0 if caption.search(c.text) else 1)
        return hits[:2]

    @staticmethod
    def _incomplete(text: str) -> Tuple[bool, bool]:
        """(starts mid-sentence, ends mid-sentence)."""
        t = text.strip()
        starts = bool(t) and t[0].islower()
        ends = bool(t) and not re.search(r"[.!?:)\]\"”’]\s*(\[\d+\])?$", t)
        return starts, ends

    def _reference_passages(self, refs: List[Tuple[str, str]], docs: List[str], cache: Dict[str, List[Any]]) -> List[Any]:
        hits: List[Any] = []
        for kind, num in refs:
            for doc_id in docs:
                hits.extend(self._reference_hits(kind, num, self._chunks(doc_id, cache)))
        return hits

    @staticmethod
    def _amounts(text: str) -> int:
        return len(_AMOUNT.findall(text or ""))

    def _statement_passages(self, query: str, docs: List[str], cache: Dict[str, List[Any]]) -> List[Any]:
        """
        The passages of the financial statements the question needs: per statement, the block
        whose line items and amounts look most like it, and the first near-best block (the
        statement itself comes before the schedules and multi-year summaries that repeat it,
        and after the management report's tables).
        """
        out: List[Any] = []
        for wanted, heading, items in _STATEMENTS:
            if not wanted.search(query or ""):
                continue
            for doc_id in docs:
                chunks = self._chunks(doc_id, cache)
                scores: List[Tuple[int, float]] = []
                for i, c in enumerate(chunks):
                    amounts = self._amounts(c.text)
                    kinds = {m.group(0).lower() for m in items.finditer(c.text)}
                    if amounts < STATEMENT_MIN_AMOUNTS or len(kinds) < 2:
                        continue
                    titled = bool(heading.search(c.section_title or "") or heading.search(c.text[:200]))
                    scores.append((i, 10 * len(kinds) + min(amounts, 80) + (30 if titled else 0)))
                if not scores:
                    continue
                best, top = max(scores, key=lambda t: t[1])
                page = chunks[best].page_number
                before = [chunks[best - 1]] if best > 0 and chunks[best - 1].page_number == page else []
                after = [chunks[best + 1]] if best + 1 < len(chunks) and chunks[best + 1].page_number == page else []
                block = ([chunks[best]] + (before or after))[:STATEMENT_PASSAGES]
                first = min(i for i, score in scores if score >= 0.85 * top)
                if all(c.chunk_id != chunks[first].chunk_id for c in block):
                    block.append(chunks[first])
                out.extend(block)
        return out[:MAX_STATEMENT_PASSAGES]

    def _neighbours(self, ch: Dict[str, Any], cache: Dict[str, List[Any]]) -> List[Any]:
        """The passage after (and/or before) a top passage that is cut mid-sentence or very short."""
        starts_mid, ends_mid = self._incomplete(ch["text"])
        short = len(ch["text"].split()) < 60
        if not (starts_mid or ends_mid or short):
            return []
        ordered = self._chunks(ch["doc_id"], cache)
        index = next((i for i, c in enumerate(ordered) if c.chunk_id == ch["chunk_id"]), None)
        if index is None:
            return []
        out = []
        if (ends_mid or short) and index + 1 < len(ordered):
            out.append(ordered[index + 1])
        if starts_mid and index > 0:
            out.append(ordered[index - 1])
        return out

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        started = time.perf_counter()
        retrieved = sorted([c for c in (state.get("chunk_context") or []) if _real(c)],
                           key=lambda c: -float(c.get("score") or 0))
        have = {c["chunk_id"] for c in retrieved}
        cache: Dict[str, List[Any]] = {}
        added: List[Dict[str, Any]] = []

        def add(chunk: Any, score: float, method: str) -> None:
            if chunk.chunk_id not in have:
                have.add(chunk.chunk_id)
                added.append({**chunk.model_dump(), "score": round(score, 4), "retrieval_method": method})

        scope = [d for d in (state.get("document_ids") or []) if d]
        docs = (scope or list(dict.fromkeys(c["doc_id"] for c in retrieved)))[:MAX_DOCS]
        top_score = float(retrieved[0].get("score") or 1.0) if retrieved else 1.0
        refs = self.references(state.get("user_query", ""))
        for hit in self._reference_passages(refs, docs, cache):
            add(hit, top_score, "reference")
        referenced = len(added)
        for hit in self._statement_passages(state.get("user_query", ""), docs, cache):
            add(hit, top_score * 0.9, "reference")
        statements = len(added) - referenced
        found = len(added)
        for ch in retrieved[:TOP_PASSAGES]:
            for neighbour in self._neighbours(ch, cache):
                add(neighbour, float(ch.get("score") or 0) * 0.9, "layout_context")

        parts = []
        if refs:
            parts.append(f"{referenced} passage(s) for " + ", ".join(f"{k} {n}" for k, n in refs))
        if statements:
            parts.append(f"{statements} passage(s) of the financial statements")
        if len(added) > found:
            parts.append(f"{len(added) - found} neighbouring passage(s)")
        detail = "; ".join(parts) or "Passages were complete; nothing added."
        return {"chunk_context": added,
                "agent_traces": [trace("document_intelligence", "completed" if added else "skipped", detail, started)]}
