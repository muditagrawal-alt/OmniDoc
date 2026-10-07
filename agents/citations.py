"""
Numbered evidence list shared by the synthesis, visualization, math and verification steps.

Every consumer builds the list with :func:`build_sources` from the same workflow state, so a
citation ``[n]`` refers to the same evidence item in the answer, in charts and in the
groundedness check. Order: retrieved evidence (chunks, then graph triples) -> calculations
-> conflict notes -> figure analyses -> web results.
"""
import re
import json
from typing import Any, Dict, List, Optional, Tuple

SNIPPET_CHARS = 320
PROMPT_TEXT_CHARS = 1600
MAX_EVIDENCE_ITEMS = 12

KIND_BY_SOURCE_TYPE = {
    "vector_chunk": "chunk",
    "chunk": "chunk",
    "table_row": "chunk",
    "kg_triple": "graph",
    "graph": "graph",
    "vision_element": "visual",
    "visual": "visual",
    "web": "web",
}

KIND_LABELS = {
    "chunk": "document passage",
    "graph": "knowledge-graph relation",
    "math": "verified calculation",
    "visual": "figure analysis",
    "web": "web result",
    "conflict": "conflict note",
}

_GENERIC_SECTIONS = {"", "general", "document body", "raw content", "none"}


def is_real_chunk(ch: Any) -> bool:
    """chunk_context may also carry non-chunk bookkeeping dicts; only real passages count."""
    return isinstance(ch, dict) and bool(str(ch.get("text") or "").strip()) and bool(ch.get("chunk_id"))


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _page(value: Any) -> Optional[int]:
    try:
        p = int(value)
        return p if p > 0 else None
    except (TypeError, ValueError):
        return None


def _score(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def _chunk_title(section: str, page: Optional[int]) -> str:
    if section and section.strip().lower() not in _GENERIC_SECTIONS and not re.fullmatch(r"page \d+", section.strip().lower()):
        return section.strip()[:120]
    return f"Page {page}" if page else "Document passage"


def _new_source(kind: str, text: str, *, doc_id: str = "", chunk_id: str = "", page: Optional[int] = None,
                section: str = "", title: str = "", score: Optional[float] = None) -> Dict[str, Any]:
    return {
        "kind": kind,
        "doc_id": str(doc_id or ""),
        "chunk_id": str(chunk_id or ""),
        "page": page,
        "section": str(section or ""),
        "title": title or KIND_LABELS.get(kind, kind),
        "snippet": _snippet(text),
        "score": score,
        "_text": str(text or "")[:PROMPT_TEXT_CHARS],
    }


def _from_evidence_item(item: Any) -> Dict[str, Any]:
    prov = _get(item, "provenance", {}) or {}
    stype = str(_get(item, "source_type", "vector_chunk") or "vector_chunk")
    kind = KIND_BY_SOURCE_TYPE.get(stype, "chunk")
    content = str(_get(item, "content", "") or "")
    page = _page(prov.get("page", prov.get("page_no", prov.get("page_number"))))
    section = str(prov.get("section", prov.get("section_title", "")) or "")
    if kind == "graph":
        src = prov.get("source_name") or ""
        tgt = prov.get("target_name") or ""
        rel = prov.get("relation") or ""
        title = f"{src} → {rel} → {tgt}" if src and tgt and rel else _snippet(content, 80)
    else:
        title = _chunk_title(section, page)
    chunk_id = prov.get("chunk_id") or (_get(item, "source_id", "") if kind == "chunk" else "")
    return _new_source(kind, content, doc_id=prov.get("doc_id", ""), chunk_id=chunk_id, page=page,
                       section=section, title=title, score=_score(_get(item, "relevance_score")))


def _chunk_sources(chunks: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    for ch in chunks or []:
        if not is_real_chunk(ch):
            continue
        cid = str(ch["chunk_id"])
        if cid not in best or (ch.get("score") or 0) > (best[cid].get("score") or 0):
            best[cid] = ch
    ordered = sorted(best.values(), key=lambda c: float(c.get("score") or 0.0), reverse=True)[:limit]
    out = []
    for ch in ordered:
        page = _page(ch.get("page_number"))
        section = str(ch.get("section_title") or "")
        out.append(_new_source("chunk", ch["text"], doc_id=ch.get("doc_id", ""), chunk_id=ch["chunk_id"],
                               page=page, section=section, title=_chunk_title(section, page),
                               score=_score(ch.get("score"))))
    return out


def _graph_sources(graph_context: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for g in graph_context or []:
        if not isinstance(g, dict):
            continue
        for e in g.get("edges", []) or []:
            src = e.get("source_name") or e.get("source") or ""
            tgt = e.get("target_name") or e.get("target") or ""
            rel = e.get("relation") or ""
            key = (src.lower(), rel.lower(), tgt.lower())
            if not (src and tgt and rel) or key in seen:
                continue
            seen.add(key)
            desc = e.get("description") or ""
            text = f"{src} —{rel}→ {tgt}" + (f": {desc}" if desc else "")
            out.append(_new_source("graph", text, doc_id=e.get("doc_id", ""), chunk_id=e.get("chunk_id", ""),
                                   page=_page(e.get("page")), section=e.get("section", "") or "",
                                   title=f"{src} → {rel} → {tgt}", score=_score(e.get("score"))))
            if len(out) >= limit:
                return out
    return out


def _math_sources(math_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for mr in math_results or []:
        if not isinstance(mr, dict) or mr.get("exact_result") is None:
            continue
        task = str(mr.get("task") or "Calculation")
        units = mr.get("units") or ""
        inputs = mr.get("inputs") or {}
        text = (f"Calculation: {task}. Result = {mr.get('exact_result')} {units}".strip()
                + f". Formula: {mr.get('formula', '')}. Inputs: {json.dumps(inputs, default=str)}")
        if mr.get("assumptions"):
            text += ". Assumptions: " + "; ".join(str(a) for a in mr["assumptions"])
        out.append(_new_source("math", text, title=task[:120]))
    return out


def _conflict_sources(conflicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for c in conflicts or []:
        if not isinstance(c, dict):
            continue
        claim = str(c.get("conflicting_claim") or "Conflicting statements")
        text = (f"Conflict: {claim}. Status: {c.get('resolution_status', 'unresolved_uncertainty')}. "
                f"Rationale: {c.get('rationale', '')}")
        ev_a, ev_b = c.get("evidence_a") or {}, c.get("evidence_b") or {}
        doc = (ev_a.get("provenance") or {}).get("doc_id", "") if isinstance(ev_a, dict) else ""
        if isinstance(ev_a, dict) and isinstance(ev_b, dict):
            text += f" | A: {ev_a.get('content', '')[:300]} | B: {ev_b.get('content', '')[:300]}"
        out.append(_new_source("conflict", text, doc_id=doc, title=claim[:120]))
    return out


def _visual_sources(visual_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for v in visual_context or []:
        if not isinstance(v, dict) or not v.get("analysis"):
            continue
        out.append(_new_source("visual", v["analysis"], doc_id=v.get("doc_id", ""), page=_page(v.get("page")),
                               title=str(v.get("caption") or v.get("figure_id") or "Figure analysis")[:120]))
    return out


def _web_sources(web_context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for w in web_context or []:
        if not isinstance(w, dict):
            continue
        text = str(w.get("snippet") or w.get("content") or "")
        if not text:
            continue
        src = _new_source("web", text, title=str(w.get("title") or w.get("url") or "Web result")[:120])
        if w.get("url"):
            src["url"] = str(w["url"])
        out.append(src)
    return out


def build_sources(
    evidence_package: Any = None,
    chunk_context: Optional[List[Dict[str, Any]]] = None,
    graph_context: Optional[List[Dict[str, Any]]] = None,
    math_results: Optional[List[Dict[str, Any]]] = None,
    conflicts: Optional[List[Dict[str, Any]]] = None,
    visual_context: Optional[List[Dict[str, Any]]] = None,
    web_context: Optional[List[Dict[str, Any]]] = None,
    max_evidence: int = MAX_EVIDENCE_ITEMS,
) -> List[Dict[str, Any]]:
    """
    Builds the ordered, numbered evidence list. Each entry carries the public source keys
    (n, kind, doc_id, chunk_id, page, section, title, snippet, score) plus a private
    ``_text`` (longer evidence text for prompts) that :func:`public_sources` strips.
    """
    sources: List[Dict[str, Any]] = []
    items = list(_get(evidence_package, "items", []) or [])
    if items:
        sources.extend(_from_evidence_item(it) for it in items[:max_evidence])
    else:
        chunk_srcs = _chunk_sources(chunk_context or [], limit=max_evidence)
        sources.extend(chunk_srcs)
        sources.extend(_graph_sources(graph_context or [], limit=max(0, min(4, max_evidence - len(chunk_srcs)))))
    sources.extend(_math_sources(math_results or []))
    sources.extend(_conflict_sources(conflicts or []))
    sources.extend(_visual_sources(visual_context or []))
    sources.extend(_web_sources(web_context or []))
    for i, s in enumerate(sources, 1):
        s["n"] = i
    return sources


def sources_from_state(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return build_sources(
        evidence_package=state.get("evidence_package"),
        chunk_context=state.get("chunk_context", []),
        graph_context=state.get("graph_context", []),
        math_results=state.get("math_results", []),
        conflicts=state.get("conflicts", []),
        visual_context=state.get("visual_context", []),
        web_context=state.get("web_context", []),
    )


def public_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drops private keys; key order follows the documented contract."""
    keys = ("n", "kind", "doc_id", "chunk_id", "page", "section", "title", "snippet", "score")
    out = []
    for s in sources:
        d = {k: s.get(k) for k in keys}
        if s.get("url"):
            d["url"] = s["url"]
        out.append(d)
    return out


def format_evidence_block(sources: List[Dict[str, Any]], kinds: Optional[Tuple[str, ...]] = None) -> str:
    """Renders sources as '[n] (label · doc · p. X · section) text' blocks for prompts."""
    blocks = []
    for s in sources:
        if kinds and s["kind"] not in kinds:
            continue
        meta = [KIND_LABELS.get(s["kind"], s["kind"])]
        if s.get("doc_id"):
            meta.append(s["doc_id"])
        if s.get("page"):
            meta.append(f"p. {s['page']}")
        if s.get("section") and s["kind"] in ("chunk", "graph") and s["section"].lower() not in _GENERIC_SECTIONS:
            meta.append(s["section"][:80])
        text = re.sub(r"[ \t]+", " ", s.get("_text") or s.get("snippet") or "").strip()
        blocks.append(f"[{s['n']}] ({' · '.join(meta)})\n{text}")
    return "\n\n".join(blocks)


# ----------------------------------------------------------------------------
# Citation normalisation for generated answers
# ----------------------------------------------------------------------------

_MATH_OR_CODE_RE = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+\$|```.*?```|`[^`\n]+`)", re.DOTALL)
_LIST_CITE_RE = re.compile(r"\[\s*(\d{1,3}(?:\s*[,;]\s*\d{1,3})+)\s*\]")
_RANGE_CITE_RE = re.compile(r"\[\s*(\d{1,3})\s*[-–—]\s*(\d{1,3})\s*\]")
_LABEL_CITE_RE = re.compile(r"\[\s*(?:source|evidence|ref|reference|doc|item|citation)s?\s*[:#]?\s*(\d{1,3})\s*\]", re.IGNORECASE)
_FULLWIDTH_CITE_RE = re.compile(r"[【［]\s*(\d{1,3})\s*[】］]")
_SINGLE_CITE_RE = re.compile(r"\[(\d{1,4})\](?!\()")
_TRAILING_REFS_RE = re.compile(
    r"\n+(?:#{1,6}\s*|\*\*)?(?:sources|references|citations|evidence used)\s*:?\**\s*\n(?:\s*(?:[-*]\s*)?\[\d+\][^\n]*\n?)+\s*$",
    re.IGNORECASE,
)


def _normalize_segment(seg: str, n_max: int) -> str:
    def valid(nums: List[int]) -> bool:
        return all(1 <= x <= n_max for x in nums)

    def expand_list(m: "re.Match") -> str:
        nums = [int(x) for x in re.split(r"\s*[,;]\s*", m.group(1).strip())]
        return "".join(f"[{x}]" for x in nums) if valid(nums) else m.group(0)

    def expand_range(m: "re.Match") -> str:
        a, b = int(m.group(1)), int(m.group(2))
        if a < b and b - a <= 10 and valid([a, b]):
            return "".join(f"[{x}]" for x in range(a, b + 1))
        return m.group(0)

    seg = _FULLWIDTH_CITE_RE.sub(lambda m: f"[{m.group(1)}]", seg)
    seg = _LABEL_CITE_RE.sub(lambda m: f"[{m.group(1)}]", seg)
    seg = _LIST_CITE_RE.sub(expand_list, seg)
    seg = _RANGE_CITE_RE.sub(expand_range, seg)
    # Drop citations outside 1..N (they point at nothing).
    seg = _SINGLE_CITE_RE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_max else "", seg)
    seg = re.sub(r"(\[\d+\])(?:\s*\1)+", r"\1", seg)          # [2][2] -> [2]
    seg = re.sub(r"[ \t]+([.,;:])", r"\1", seg)                # "word [9]." -> "word."
    return seg


def normalize_citations(text: str, n_max: int) -> str:
    """
    Canonicalises citation markers to [n] / [n][m], removes markers that are > N (or < 1),
    leaves LaTeX and code untouched, and drops a trailing references list (the UI renders
    sources itself).
    """
    if not text:
        return text
    text = _TRAILING_REFS_RE.sub("", text.rstrip()) if n_max else text
    parts = _MATH_OR_CODE_RE.split(text)
    out = []
    for i, part in enumerate(parts):
        out.append(part if i % 2 == 1 else _normalize_segment(part, n_max))
    return "".join(out).strip()


def cited_numbers(text: str) -> List[int]:
    nums = set()
    for i, part in enumerate(_MATH_OR_CODE_RE.split(text or "")):
        if i % 2 == 0:
            nums.update(int(m.group(1)) for m in _SINGLE_CITE_RE.finditer(part))
    return sorted(nums)
