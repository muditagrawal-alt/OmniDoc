"""
Temporal Reasoning Agent for OmniDoc.

Dates the evidence without model calls: every sentence of the retrieved passages that
mentions a date (2024-03-15, 15 March 2024, March 2024, Q3 2024, FY2023-24, 2009) gets a
sortable date. Then:

* when the question limits a period ("in 2023", "between 2019 and 2021", "since 2020"),
  passages whose dates all fall outside it are dropped from the evidence (as long as
  enough evidence remains);
* for timeline questions, the dated statements are ordered and handed to the writer as a
  chronology, each linked to the passage it came from so it can be cited.
"""
import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.state import AgentWorkflowState
from agents.llm_utils import trace

logger = logging.getLogger("OmniDoc.TemporalReasoning")

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b"), "dmy"),
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})\b"), "mdy"),
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{4})\b"), "my"),
    (re.compile(r"\bQ([1-4])\s*(?:FY\s*)?(\d{4})\b", re.I), "q"),
    (re.compile(r"\bFY\s*'?(\d{2,4})(?:\s*[-–/]\s*(\d{2,4}))?\b", re.I), "fy"),
    (re.compile(r"(?<![\d.,])(1[89]\d\d|20\d\d)(?!\d|[.,]\d|%)"), "year"),
]
MAX_TIMELINE = 15


def dates_in(text: str) -> List[Tuple[str, str]]:
    """(sort key "YYYY-MM-DD", the text as written) for each date in a text; most specific first."""
    found: List[Tuple[str, str]] = []
    taken: List[Tuple[int, int]] = []
    for pattern, kind in _PATTERNS:
        for m in pattern.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            key = _key(kind, m.groups())
            if key:
                found.append((key, m.group(0)))
                taken.append((m.start(), m.end()))
    return found


def _key(kind: str, g: Tuple[str, ...]) -> Optional[str]:
    try:
        if kind == "iso":
            y, mo, d = int(g[0]), int(g[1]), int(g[2])
        elif kind == "dmy":
            mo = _MONTHS.get(g[1][:3].lower())
            y, d = int(g[2]), int(g[0])
        elif kind == "mdy":
            mo = _MONTHS.get(g[0][:3].lower())
            y, d = int(g[2]), int(g[1])
        elif kind == "my":
            mo = _MONTHS.get(g[0][:3].lower())
            y, d = int(g[1]), 1
        elif kind == "q":
            y, mo, d = int(g[1]), 3 * (int(g[0]) - 1) + 1, 1
        elif kind == "fy":
            y = int(g[0]) if len(g[0]) == 4 else 2000 + int(g[0])
            mo, d = 4, 1
        else:
            y, mo, d = int(g[0]), 1, 1
        if not mo or not (1800 <= y <= 2100) or not (1 <= mo <= 12) or not (1 <= d <= 31):
            return None
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except (TypeError, ValueError):
        return None


def _bound(value: Any, end: bool) -> Optional[str]:
    v = str(value or "").strip()
    if not v:
        return None
    if re.fullmatch(r"\d{4}", v):
        return f"{v}-12-31" if end else f"{v}-01-01"
    if re.fullmatch(r"\d{4}-\d{2}", v):
        return f"{v}-31" if end else f"{v}-01"
    return v[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v[:10]) else None


class TemporalReasoningAgent:
    """Dates the evidence, applies the question's time range and orders events."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    @staticmethod
    def _date_passages(chunks: List[Dict[str, Any]], start: Optional[str], end: Optional[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Dated sentences of the passages, and the passages whose dates all fall outside the range."""
        entries: List[Dict[str, Any]] = []
        outside: List[str] = []
        for ch in chunks:
            keys = []
            for sentence in _SENT.split(ch["text"]):
                for key, written in dates_in(sentence)[:2]:
                    keys.append(key)
                    entries.append({"date": key, "written": written, "text": sentence.strip()[:300],
                                    "chunk_id": ch["chunk_id"], "doc_id": ch.get("doc_id", ""), "page": ch.get("page_number")})
            if keys and (start or end) and all((start and k < start) or (end and k > end) for k in keys):
                outside.append(ch["chunk_id"])
        return entries, outside

    @staticmethod
    def _chronology(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen, timeline = set(), []
        for e in sorted(entries, key=lambda e: e["date"]):
            sig = (e["date"], e["text"][:80])
            if sig not in seen:
                seen.add(sig)
                timeline.append(e)
        return timeline[:MAX_TIMELINE]

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        started = time.perf_counter()
        needs = state.get("needs") or {}
        semantic_q = state.get("semantic_query")
        tr = state.get("time_filter") or getattr(semantic_q, "temporal_constraints", None) or {}
        start, end = _bound(tr.get("start"), False), _bound(tr.get("end"), True)
        chunks = [c for c in (state.get("chunk_context") or []) if isinstance(c, dict) and c.get("chunk_id") and c.get("text")]
        if not chunks or not (start or end or needs.get("timeline")):
            return {}

        entries, outside = self._date_passages(chunks, start, end)
        if len(chunks) - len(set(outside)) < 2:  # never drop so much that too little evidence is left
            outside = []
        in_range = [e for e in entries if not ((start and e["date"] < start) or (end and e["date"] > end))]
        timeline = self._chronology(in_range) if needs.get("timeline") else []

        parts = []
        if start or end:
            parts.append(f"range {start or '…'} to {end or '…'}: {len(set(outside))} passage(s) outside it set aside")
        if timeline:
            parts.append(f"{len(timeline)} dated statement(s) ordered")
        out: Dict[str, Any] = {
            "time_filter": {"start": start, "end": end, "exclude_chunk_ids": sorted(set(outside))},
            "agent_traces": [trace("temporal_reasoning", "completed", "; ".join(parts) or "No dates found.", started)],
        }
        if timeline:
            out["timeline"] = timeline
        return out
