"""
Document Intelligence Agent for OmniDoc.

Layout-aware context, without model calls:

* follows explicit references in the question ("Table 3", "Figure 2", "section 4.1",
  "page 12", "clause 7", "slide 5") to the passages that contain them, even when the
  search did not rank them;
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
MAX_DOCS = 3
TOP_PASSAGES = 3


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
        out = []
        for kind, num in _REF.findall(query or ""):
            kind = kind.lower().rstrip(".") if kind.lower() != "p." else "page"
            if (kind, num) not in out:
                out.append((kind, num))
        return out[:4]

    def _reference_hits(self, kind: str, num: str, chunks: List[Any]) -> List[Any]:
        if kind == "page":
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
        found = len(added)
        for ch in retrieved[:TOP_PASSAGES]:
            for neighbour in self._neighbours(ch, cache):
                add(neighbour, float(ch.get("score") or 0) * 0.9, "layout_context")

        parts = []
        if refs:
            parts.append(f"{found} passage(s) for " + ", ".join(f"{k} {n}" for k, n in refs))
        if len(added) > found:
            parts.append(f"{len(added) - found} neighbouring passage(s)")
        detail = "; ".join(parts) or "Passages were complete; nothing added."
        return {"chunk_context": added,
                "agent_traces": [trace("document_intelligence", "completed" if added else "skipped", detail, started)]}
