"""
Document Intelligence Agent for OmniDoc.

Layout-aware context, without model calls:

* follows explicit references in the question ("Table 3", "Figure 2", "section 4.1",
  "page 12", "pages 16 and 18", "page(1)", "page nine", "the last page", "the cover page",
  "clause 7", "slide 5") to the passages that contain them, even when the search did not
  rank them; a page named by number is given both at that position and, when the pages are
  numbered in print from a later page (after a cover and contents), where that number is printed;
* adds the financial statements a question names ("statement of financial position") or
  needs for the figures it asks about (inventory, COGS, capex...), recognised by their line
  items and amounts: the text search rarely ranks a page of numbers first;
* gives those statements and the pages a question names as whole pages: a balance sheet
  split into passages loses the rows the question needs (and one split over two pages is
  given both);
* adds a survey's table of sample sizes when the question asks how many people gave an
  answer (the count is the group's percentage of its sample), and a filing's cover page when
  it asks which securities are registered on an exchange;
* adds the neighbouring passage when a top passage stops mid-sentence or starts in the
  middle of one, so the writer sees the whole statement;
* notes the names in the question (proper nouns, acronyms, quoted terms) that appear nowhere
  in the document: a question about "MMDU" put to a paper that never mentions it is one the
  document cannot answer, whatever the search returns.

Added passages carry the relevance of the passage they belong to and are marked
``layout_context`` or ``reference``; whole pages are also marked ``full_page``.
"""
import os
import re
import time
import difflib
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.state import AgentWorkflowState, RetrievedChunk
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
                r"cash ratio|cash conversion cycle|liquidity|solvency|leverage|debt[- ]to[- ]equity|asset turnover|"
                r"return on (average )?(total |common )?(shareholders'? |stockholders'? )?(assets|equity)|\bRO[AE]\b|accrued|accruals?\b|"
                r"capital[- ]intensi|\bPPN?E\b|\b(total|net|average( total)?) debt\b|debt (on|in) (the |its )?balance sheet|"
                r"inventor(y|ies)|receivables?|payables?|total (assets|liabilities|debt)|(shareholders|stockholders)'? equity|"
                r"PP&E|property,? plant|book value|days (payable|sales|inventory)", re.I),
     re.compile(r"balance sheets?|statements? of (consolidated )?financial (position|condition)", re.I),
     re.compile(r"total current assets|total assets|total current liabilities|total liabilities|(stockholders|shareholders)['’]? equity|"
                r"retained earnings|accounts payable|inventories|property(, plant)? and equipment|cash and cash equivalents", re.I)),
    (re.compile(r"income statements?|statements? of (consolidated )?(income|operations|earnings)|profit (and|&) loss|\bP&L\b|"
                r"cash conversion cycle|asset turnover|\bRO[AE]\b|interest coverage|capital[- ]intensi|interest (to|paid|cost|burden)|"
                r"effective tax|tax rate|income tax(es)?|provision for (income )?taxes|"
                r"revenues?|net sales|COGS|cost of (goods sold|sales|revenues?)|gross (profit|margin)|operating (income|margin|profit)|"
                r"net (income|earnings|margin|loss)|EBIT(DA)?|earnings per share|\bEPS\b|interest expense|turnover|return on", re.I),
     re.compile(r"statements? of (consolidated )?(income|operations|earnings|comprehensive income)|income statements?|profit (and|&) loss", re.I),
     re.compile(r"net sales|total (net )?revenues?|cost of (sales|revenues?|goods sold)|gross (profit|margin)|operating (income|profit)|"
                r"income before income taxes|provision for income taxes|net (income|earnings)|per (common )?share|diluted", re.I)),
    (re.compile(r"cash ?flows?|capex|capital expenditures?|purchases? of property|dividends? paid|share repurchases?|"
                r"(operating|investing|financing) activities|capital[- ]intensi", re.I),
     re.compile(r"statements? of (consolidated )?cash flows?|cash flows? statements?", re.I),
     re.compile(r"operating activities|investing activities|financing activities|net cash (provided|used)|"
                r"depreciation and amortization|capital expenditures|purchases? of property|dividends paid|end of (the )?(year|period)", re.I)),
)
MAX_STATEMENT_PAGES = 5   # per question
# What the first and the last page of each statement hold: a statement split over two pages (assets on
# one, liabilities and equity on the next) is given whole.
_STATEMENT_ENDS = (
    (re.compile(r"total (current )?assets", re.I),
     re.compile(r"total (current )?liabilities|total (stockholders|shareholders)['’]? equity", re.I)),
    (re.compile(r"net sales|revenues?", re.I), re.compile(r"net (income|earnings|loss)", re.I)),
    (re.compile(r"operating activities", re.I), re.compile(r"financing activities|end of (the )?(year|period)", re.I)),
)
# The primary statements sit next to each other (balance sheet, income, cash flows): the pages
# are chosen from the window of this many pages where the three score best together, which
# passes over the summaries elsewhere that repeat their line items.
STATEMENT_WINDOW = 7
# Five-year summaries ("Selected Financial Data") repeat the line items for many years.
_YEAR = re.compile(r"\b(?:19|20)\d\d\b")
# A whole page given to the writer is cut after this many characters (a 10-K balance sheet is 3-6,000).
FULL_PAGE_CHARS = 7000
STATEMENT_MIN_AMOUNTS = 6  # a statement is full of amounts (44,538 / 3.46); a contents page has page numbers
_AMOUNT = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+")
# "How many Democrats said ...": a survey's counts are its percentages of the groups' sample sizes, which its
# methodology section tabulates ("Unweighted sample size ... Plus or minus ...").
PEOPLE_COUNT = re.compile(r"\bhow many\b(?:(?!\?).){0,60}?\b(people|persons|adults|respondents|voters|americans|participants|"
                          r"democrats?|republicans?|independents|men|women|parents|users|residents|citizens|latinos?|"
                          r"hispanics?|immigrants?)\b", re.I)
_ASKS_SHARE = re.compile(r"percent|%|proportion|share of|ratio", re.I)
SAMPLE_SIZE = re.compile(r"sample size|number of (respondents|interviews)", re.I)
_SAMPLING_ERROR = re.compile(r"margin of (sampling )?error|plus or minus", re.I)


def asks_people_count(query: str) -> bool:
    """A question asking how many people gave an answer (a count, not a percentage)."""
    return bool(PEOPLE_COUNT.search(query or "")) and not _ASKS_SHARE.search(query or "")


def survey_sample_table(text: str) -> bool:
    """Text holding a survey's sample sizes and sampling error."""
    return bool(SAMPLE_SIZE.search(text or "")) and bool(_SAMPLING_ERROR.search(text or ""))


# A filing's cover page lists the securities registered on an exchange ("Securities registered pursuant to Section
# 12(b) of the Act: Title of each class, Trading symbol, Name of each exchange").
_REGISTERED_LIST = re.compile(r"section 12\(b\)|title of each class", re.I)
COVER_PAGES = 5  # the cover page is among the first pages
_QUOTED = re.compile(r'["“]([^"”]{2,60})["”]')
_CAPITALISED = re.compile(r"\b[A-Z][\w&.\-]*[A-Za-z0-9](?:\s+(?:of\s+|the\s+|and\s+|&\s+)?[A-Z][\w&.\-]*[A-Za-z0-9])*")
# Capitalised words that are not names: question words, sentence starters, financial shorthand.
_NOT_NAMES = set("""what how which who whom whose when where why is are was were does do did can could should would will
has have had the a an in on of for to from by with and or if according based compared give return round please answer
calculate using use considering assuming directly list name describe explain provide find tell among between as at this
that these those it its there fy usd us gaap non-gaap ar ap cogs pp&e ebit ebitda eps fcf sg&a r&d d&a roa roe dpo dso
dio cagr yoy ttm ceo cfo ppe ppne capex opex inc corp ltd plc llc co january february march april may june july august september october
november december monday tuesday wednesday thursday friday saturday sunday i yes no""".split())


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def question_names(query: str) -> List[str]:
    """Proper nouns, acronyms and quoted terms of a question, for checking that the document mentions them."""
    names = [m.group(1).strip() for m in _QUOTED.finditer(query or "")]
    for m in _CAPITALISED.finditer(query or ""):
        words = m.group(0).split()
        while words and words[0].lower() in _NOT_NAMES:
            words = words[1:]
        if not words or (len(words) == 1 and (len(words[0]) < 3 or words[0].lower() in _NOT_NAMES)):
            continue
        if re.fullmatch(r"(FY|Q[1-4]|H[12])\d*|\d[\d\-]*s?", words[0]):
            continue  # a period ("Q2 of FY2023", "FY2022"), not a name
        names.append(" ".join(words))
    return list(dict.fromkeys(n for n in names if _squash(n)))[:8]


def name_variants(name: str, text: str, limit: int = 2) -> List[str]:
    """
    Names in the text that differ from a name of several words in one of them ("MQA Executive Leadership"
    for "HAQ Executive Leadership"): another thing than the one asked about. A misspelt long word
    ("Sytems") is not another name; a short one that differs (HAQ / MQA, III / II) is.
    """
    words = (name or "").split()
    out: List[str] = []
    if len(words) < 2:
        return out
    for i, word in enumerate(words):
        pattern = r"(?<![\w&.\-])" + r"\s+".join(r"([\w&.\-]+)" if j == i else re.escape(w) for j, w in enumerate(words)) + r"(?![\w&\-])"
        for m in re.finditer(pattern, text or "", re.I):
            other, asked = m.group(1).lower(), word.lower()
            if other == asked or (min(len(other), len(asked)) > 4 and difflib.SequenceMatcher(None, other, asked).ratio() >= 0.75):
                continue
            variant = re.sub(r"\s+", " ", m.group(0))
            if variant.lower() not in (v.lower() for v in out):
                out.append(variant)
            if len(out) >= limit:
                return out
    return out


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


# A page number printed in a page's header or footer: a number of one to three digits standing alone
# (not part of a year, a decimal, a date or a range).
_PRINTED_NUMBER = re.compile(r"(?<![\d.,/:\-])(\d{1,3})(?![\d]|[.,:/\-]\d)")


def printed_page_offset(texts: Dict[int, str]) -> int:
    """
    How far the pages' positions run ahead of the numbers printed on them (a cover and contents
    pages before page 1): the offset most pages agree on, read from the small numbers at the start
    and end of their text; 0 when the pages are not numbered or the numbers are their positions.
    """
    votes: Dict[int, int] = {}
    numbered = 0  # pages with a number at either end (front matter often has none, or roman numerals)
    for page, text in texts.items():
        t = (text or "").strip()
        ends = t[:40] + " | " + t[-40:]
        offsets = {page - int(n) for n in _PRINTED_NUMBER.findall(ends) if 0 < int(n) <= page}
        numbered += bool(offsets)
        for offset in offsets:
            votes[offset] = votes.get(offset, 0) + 1
    if not votes:
        return 0
    best = max(votes, key=lambda o: (votes[o], -o))
    return best if best > 0 and votes[best] >= max(3, 0.5 * numbered) else 0


_OFFSETS: Dict[Tuple[str, float], int] = {}


def pdf_page_offset(path: str, max_pages: int = 120) -> int:
    """The printed-page offset of a PDF, from the text of its pages with their headers and footers (0 if unknown)."""
    try:
        key = (path, os.path.getmtime(path))
        if key not in _OFFSETS:
            import fitz
            with fitz.open(path) as doc:
                texts = {i + 1: doc[i].get_text("text", sort=True) for i in range(min(len(doc), max_pages))}
            _OFFSETS[key] = printed_page_offset(texts)
        return _OFFSETS[key]
    except Exception as e:
        logger.debug(f"Could not read the page numbers of {path}: {e}")
        return 0


def page_texts(chunks: List[Any]) -> Dict[int, str]:
    """The text of every page, its passages joined in reading order."""
    out: Dict[int, str] = {}
    for c in chunks:
        out[c.page_number] = (out[c.page_number] + " " + c.text) if c.page_number in out else c.text
    return out


def numbered_pages(query: str) -> List[str]:
    """The pages a question names by their number ("page 9", "page nine"), which may be the number printed on
    the page; not "the cover page" or "the third page", which name a position."""
    out: List[str] = []
    for m in _PAGE_LIST.finditer(query or ""):
        out += [str(n) for n in [_number(m.group(1))] + [_number(t) for t in re.findall(_NUM, m.group(2) or "", re.I)] if n]
    return [n for n in dict.fromkeys(out) if n in page_references(query)]


def _real(ch: Dict[str, Any]) -> bool:
    return isinstance(ch, dict) and bool(ch.get("chunk_id")) and bool(ch.get("text"))


def _strip_overlap(previous: str, text: str, max_words: int = 80) -> str:
    """Drops the words a passage repeats from the end of the one before it (passages overlap)."""
    prev_words, words = previous.split(), text.split()
    for k in range(min(max_words, len(prev_words), len(words) - 1), 4, -1):
        if prev_words[-k:] == words[:k]:
            return " ".join(words[k:])
    return text


def page_passage(chunks: List[Any], doc_id: str, page: int) -> Optional[RetrievedChunk]:
    """One passage holding the whole text of a page (its passages joined in reading order)."""
    parts, previous = [], ""
    for c in chunks:
        if c.page_number == page:
            parts.append(_strip_overlap(previous, c.text) if previous else c.text)
            previous = c.text
    if not parts:
        return None
    first = next(c for c in chunks if c.page_number == page)
    return RetrievedChunk(chunk_id=f"{doc_id}_p{page}_page", doc_id=doc_id, page_number=page,
                          text=" ".join(parts)[:FULL_PAGE_CHARS], section_title=first.section_title)


class DocumentIntelligenceAgent:
    """Follows document references and adds neighbouring passages around the best hits."""

    def __init__(self, lance_store: Any = None, files_dir: Optional[str] = None):
        self.lance_store = lance_store
        self.files_dir = files_dir  # the stored uploads, for the page numbers printed in headers and footers

    def _printed_offset(self, chunks: List[Any]) -> int:
        """From the stored PDF when there is one (the passages may have lost its headers and footers), else the passages."""
        doc_id = str(chunks[0].doc_id or "")
        if self.files_dir and re.fullmatch(r"[A-Za-z0-9_\-.]+", doc_id):
            path = os.path.join(self.files_dir, doc_id + ".pdf")
            if os.path.isfile(path):
                return pdf_page_offset(path)
        return printed_page_offset(page_texts(chunks))

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

    def _reference_hits(self, kind: str, num: str, chunks: List[Any], numbered: bool = False) -> List[Any]:
        if kind == "page":
            last = max((c.page_number for c in chunks), default=0)
            page = last if num == "last" else int(num) if num.isdigit() else 0
            whole = page_passage(chunks, chunks[0].doc_id, page) if chunks and page else None
            out = [whole] if whole else []
            # "page 9" may mean the page numbered 9 in print, three pages on when a cover and contents come first.
            offset = self._printed_offset(chunks) if chunks and numbered else 0
            printed = page_passage(chunks, chunks[0].doc_id, page + offset) if offset and page + offset <= last else None
            if printed:
                printed.section_title = f"printed page {page}"
                out.append(printed)
            return out
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

    def _reference_passages(self, refs: List[Tuple[str, str]], docs: List[str], cache: Dict[str, List[Any]],
                            numbered: Optional[List[str]] = None) -> List[Any]:
        hits: List[Any] = []
        for kind, num in refs:
            for doc_id in docs:
                hits.extend(self._reference_hits(kind, num, self._chunks(doc_id, cache),
                                                 numbered=kind == "page" and num in (numbered or [])))
        return hits

    @staticmethod
    def _amounts(text: str) -> int:
        return len(_AMOUNT.findall(text or ""))

    def _statement_scores(self, chunks: List[Any]) -> List[Dict[int, float]]:
        """Per statement (balance sheet, income, cash flows): page -> how much its best passage looks like it."""
        out: List[Dict[int, float]] = []
        for _, heading, items in _STATEMENTS:
            pages: Dict[int, float] = {}
            for c in chunks:
                amounts = self._amounts(c.text)
                kinds = {m.group(0).lower() for m in items.finditer(c.text)}
                if amounts < STATEMENT_MIN_AMOUNTS or len(kinds) < 2:
                    continue
                titled = bool(heading.search(c.section_title or "") or heading.search(c.text[:200]))
                score = 10 * len(kinds) + min(amounts, 80) + (30 if titled else 0)
                if len(set(_YEAR.findall(c.text[:300]))) >= 4:
                    score *= 0.6  # a five-year summary, not the statement
                pages[c.page_number] = max(pages.get(c.page_number, 0.0), score)
            out.append(pages)
        return out

    def _statement_span(self, k: int, page: int, chunks: List[Any]) -> List[int]:
        """The statement's page, with the page before or after it when the statement starts or ends there."""
        def text(p: int) -> str:
            return " ".join(c.text for c in chunks if c.page_number == p)
        first, last = _STATEMENT_ENDS[k]
        here = text(page)
        if not first.search(here):
            before = text(page - 1)
            if first.search(before) and self._amounts(before) >= STATEMENT_MIN_AMOUNTS:
                return [page - 1, page]
        elif not last.search(here):
            after = text(page + 1)
            if last.search(after) and self._amounts(after) >= STATEMENT_MIN_AMOUNTS:
                return [page, page + 1]
        return [page]

    def _statement_passages(self, query: str, docs: List[str], cache: Dict[str, List[Any]]) -> List[Any]:
        """
        The pages of the financial statements the question needs, whole: each from the window
        of pages where the balance sheet, income statement and cash flow statement score best
        together; a statement missing from that window comes from its best page elsewhere.
        """
        query = (query or "").replace("_", " ")  # "cash_ratio"
        wanted = [k for k, (pattern, _, _) in enumerate(_STATEMENTS) if pattern.search(query)]
        pages: List[Tuple[str, int]] = []
        for doc_id in docs:
            if not wanted:
                break
            scores = self._statement_scores(self._chunks(doc_id, cache))
            starts = sorted({p for per in scores for p in per})
            if not starts:
                continue

            def window(start: int) -> float:
                return sum(max([v for p, v in per.items() if start <= p < start + STATEMENT_WINDOW], default=0.0) for per in scores)
            start = max(starts, key=lambda s0: (window(s0), -s0))
            for k in wanted:
                per = scores[k]
                if not per:
                    continue
                best = max(per, key=per.get)
                inside = [p for p in per if start <= p < start + STATEMENT_WINDOW]
                page = max(inside, key=per.get) if inside and per[max(inside, key=per.get)] >= 0.4 * per[best] else best
                for p in self._statement_span(k, page, self._chunks(doc_id, cache)):
                    if (doc_id, p) not in pages:
                        pages.append((doc_id, p))
        out = [page_passage(self._chunks(doc_id, cache), doc_id, page) for doc_id, page in pages[:MAX_STATEMENT_PAGES]]
        return [p for p in out if p]

    def _cover_passages(self, query: str, docs: List[str], cache: Dict[str, List[Any]]) -> List[Any]:
        """For a question about the securities listed on an exchange: the filing's cover page, whole."""
        from agents.finance_terms import REGISTERED
        if not REGISTERED.search(query or ""):
            return []
        out = []
        for doc_id in docs:
            chunks = self._chunks(doc_id, cache)
            pages = sorted({c.page_number for c in chunks if c.page_number <= COVER_PAGES and _REGISTERED_LIST.search(c.text)})
            whole = page_passage(chunks, doc_id, pages[0]) if pages else None
            if whole:
                out.append(whole)
        return out

    def _sample_size_passages(self, query: str, docs: List[str], cache: Dict[str, List[Any]]) -> List[Any]:
        """For "how many <people> said ..." (a count, not a percentage): the page of a survey's sample sizes, whole."""
        if not asks_people_count(query):
            return []
        out = []
        for doc_id in docs:
            chunks = self._chunks(doc_id, cache)
            tables = [c for c in chunks if survey_sample_table(c.text)]
            if tables:
                best = max(tables, key=lambda c: len(SAMPLE_SIZE.findall(c.text)) + len(_SAMPLING_ERROR.findall(c.text)))
                whole = page_passage(chunks, doc_id, best.page_number)
                if whole:
                    out.append(whole)
        return out

    def _absent_names(self, query: str, docs: List[str], cache: Dict[str, List[Any]]) -> List[str]:
        """
        Names in the question that none of the documents in scope mentions anywhere: the name
        itself is not in the text, and nor is one of its words ("Adjusted Non GAAP EBITDA" is
        present when the filing says "Adjusted EBITDA" and "non-GAAP" apart; "MMDU" is not).
        """
        names = question_names(query)
        if not names or not docs:
            return []
        text = "".join(_squash(c.text) for d in docs for c in self._chunks(d, cache))
        if not text:
            return []
        absent = []
        for name in names:
            words = [_squash(w) for w in re.findall(r"[A-Za-z0-9]+", name) if w.lower() not in _NOT_NAMES]
            if _squash(name) not in text and any(w and w not in text for w in words):
                absent.append(name)
        return absent

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
                whole = {"full_page": True} if chunk.chunk_id.endswith("_page") else {}
                added.append({**chunk.model_dump(), "score": round(score, 4), "retrieval_method": method, **whole})

        scope = [d for d in (state.get("document_ids") or []) if d]
        docs = (scope or list(dict.fromkeys(c["doc_id"] for c in retrieved)))[:MAX_DOCS]
        top_score = float(retrieved[0].get("score") or 1.0) if retrieved else 1.0
        refs = self.references(state.get("user_query", ""))
        for hit in self._reference_passages(refs, docs, cache, numbered_pages(state.get("user_query", ""))):
            add(hit, top_score, "reference")
        referenced = len(added)
        for hit in self._statement_passages(state.get("user_query", ""), docs, cache):
            add(hit, top_score * 0.9, "reference")
        statements = len(added) - referenced
        for hit in self._cover_passages(state.get("user_query", ""), docs, cache):
            add(hit, top_score * 0.9, "reference")
        for hit in self._sample_size_passages(state.get("user_query", ""), docs, cache):
            add(hit, top_score * 0.9, "reference")
        samples = len(added) - referenced - statements
        found = len(added)
        for ch in retrieved[:TOP_PASSAGES]:
            for neighbour in self._neighbours(ch, cache):
                add(neighbour, float(ch.get("score") or 0) * 0.9, "layout_context")

        absent = self._absent_names(state.get("user_query", ""), docs, cache) if scope else []
        parts = []
        if refs:
            parts.append(f"{referenced} passage(s) for " + ", ".join(f"{k} {n}" for k, n in refs))
        if statements:
            parts.append(f"{statements} page(s) of the financial statements")
        if samples:
            parts.append("the survey's sample sizes")
        if len(added) > found:
            parts.append(f"{len(added) - found} neighbouring passage(s)")
        if absent:
            parts.append("not in the document: " + ", ".join(absent))
        detail = "; ".join(parts) or "Passages were complete; nothing added."
        return {"chunk_context": added, "absent_terms": absent,
                "agent_traces": [trace("document_intelligence", "completed" if added or absent else "skipped", detail, started)]}
