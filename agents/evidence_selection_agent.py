"""
Evidence Selection and Ranking Agent for OmniDoc.
Scores every candidate (document chunks and knowledge-graph triples) with the cross-encoder
reranker, deduplicates, applies query-focused contextual compression and compiles a compact
EvidencePackage whose items carry provenance (doc_id, page, chunk_id, section) and the real
reranker relevance score.
"""
import re
import time
import logging
from typing import Dict, Any, List, Tuple

from core.state import AgentWorkflowState, EvidenceItem, EvidencePackage
from retrieval.reranker import ChunkReranker
from agents.citations import is_real_chunk
from agents.llm_utils import trace

logger = logging.getLogger("OmniDoc.EvidenceSelection")

MAX_CHUNKS = 6
MAX_TRIPLES = 3
MIN_TRIPLE_SCORE = 0.05   # graph triples are short; keep only ones the reranker finds relevant
MAX_CONTENT_CHARS = 1500

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_WORD = re.compile(r"[a-z0-9]+")


def _query_terms(query: str) -> set:
    return {w for w in _WORD.findall(query.lower()) if len(w) > 2}


def compress(text: str, query: str, budget: int = MAX_CONTENT_CHARS) -> str:
    """
    Query-focused compression: if a passage exceeds the budget, keep the sentences with the
    highest query-term overlap (in original order) instead of blindly truncating the tail.
    """
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= budget:
        return text
    sentences = _SENT_SPLIT.split(text)
    if len(sentences) <= 1:
        return text[:budget].rstrip() + "…"
    terms = _query_terms(query)
    scored = []
    for idx, s in enumerate(sentences):
        words = set(_WORD.findall(s.lower()))
        overlap = len(words & terms)
        has_number = 1 if re.search(r"\d", s) else 0
        scored.append((overlap * 2 + has_number, idx, s))
    keep, used = set(), 0
    for _, idx, s in sorted(scored, key=lambda x: (-x[0], x[1])):
        if used + len(s) + 2 > budget:
            continue
        keep.add(idx)
        used += len(s) + 2
    if not keep:
        return text[:budget].rstrip() + "…"
    out, prev = [], None
    for idx in sorted(keep):
        if prev is not None and idx != prev + 1:
            out.append("…")
        out.append(sentences[idx])
        prev = idx
    return " ".join(out)


class EvidenceSelectionAgent:
    """Reranks and compresses candidate evidence to supply minimal sufficient context."""

    def __init__(self, reranker: ChunkReranker = None):
        self.reranker = reranker or ChunkReranker()

    @staticmethod
    def _dedupe_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_id: Dict[str, Dict[str, Any]] = {}
        seen_text = set()
        for ch in chunks:
            if not is_real_chunk(ch):
                continue
            cid = str(ch["chunk_id"])
            sig = re.sub(r"\W+", "", ch["text"].lower())[:300]
            if cid in by_id:
                if float(ch.get("score") or 0) > float(by_id[cid].get("score") or 0):
                    by_id[cid] = ch
                continue
            if sig in seen_text:
                continue
            seen_text.add(sig)
            by_id[cid] = ch
        return list(by_id.values())

    @staticmethod
    def _collect_triples(graph_context: List[Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
        triples, seen = [], set()
        for g in graph_context or []:
            if not isinstance(g, dict):
                continue
            for edge in g.get("edges", []) or []:
                src = edge.get("source_name") or edge.get("source") or ""
                tgt = edge.get("target_name") or edge.get("target") or ""
                rel = edge.get("relation") or ""
                if not (src and tgt and rel):
                    continue
                key = (src.lower(), rel.lower(), tgt.lower())
                if key in seen:
                    continue
                seen.add(key)
                desc = edge.get("description") or ""
                text = f"{src} —{rel}→ {tgt}" + (f": {desc}" if desc else "")
                triples.append((text, edge))
        return triples

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Processes accumulated chunk and graph context into a ranked EvidencePackage.
        """
        started = time.perf_counter()
        semantic_q = state.get("semantic_query")
        query = getattr(semantic_q, "resolved_query", None) or state.get("user_query", "")

        chunks = self._dedupe_chunks(state.get("chunk_context", []) or [])
        triples = self._collect_triples(state.get("graph_context", []) or [])

        chunk_scores = self.reranker.score_pairs(query, [c["text"] for c in chunks]) if chunks else []
        triple_scores = self.reranker.score_pairs(query, [t for t, _ in triples]) if triples else []

        chunk_items: List[EvidenceItem] = []
        for ch, score in zip(chunks, chunk_scores):
            # Keep the better of retrieval-time (multi-query) and query-time relevance.
            prior = ch.get("score")
            if ch.get("retrieval_method") in ("neural_reranked", "lexical_reranked") and prior is not None:
                score = max(float(score), float(prior))
            cid = str(ch["chunk_id"])
            page = ch.get("page_number")
            chunk_items.append(EvidenceItem(
                evidence_id=f"ev_chunk_{cid}",
                source_type="vector_chunk",
                source_id=cid,
                content=compress(ch["text"], query),
                relevance_score=round(float(score), 4),
                authority_score=1.0,
                provenance={
                    "doc_id": ch.get("doc_id", ""),
                    "chunk_id": cid,
                    "page": page,
                    "page_no": page,
                    "section": ch.get("section_title") or "",
                    "retrieval_method": ch.get("retrieval_method", ""),
                },
            ))

        triple_items: List[EvidenceItem] = []
        for (text, edge), score in zip(triples, triple_scores):
            if score < MIN_TRIPLE_SCORE:
                continue
            src = edge.get("source_name") or edge.get("source") or ""
            tgt = edge.get("target_name") or edge.get("target") or ""
            sid = f"{edge.get('source', src)}->{edge.get('target', tgt)}"
            triple_items.append(EvidenceItem(
                evidence_id=f"ev_kg_{re.sub(r'[^A-Za-z0-9_.-]', '_', sid)}_{len(triple_items)}",
                source_type="kg_triple",
                source_id=sid,
                content=text,
                relevance_score=round(float(score), 4),
                authority_score=0.8,
                provenance={
                    "doc_id": edge.get("doc_id", ""),
                    "chunk_id": edge.get("chunk_id", ""),
                    "page": edge.get("page"),
                    "page_no": edge.get("page"),
                    "section": edge.get("section", ""),
                    "relation": edge.get("relation", ""),
                    "source_name": src,
                    "target_name": tgt,
                },
            ))

        chunk_items.sort(key=lambda x: x.relevance_score, reverse=True)
        triple_items.sort(key=lambda x: x.relevance_score, reverse=True)
        selected = chunk_items[:MAX_CHUNKS] + triple_items[:MAX_TRIPLES]
        total = len(chunks) + len(triples)

        package = EvidencePackage(
            query_id=state.get("session_id", "default"),
            items=selected,
            total_candidates_considered=total,
            selected_count=len(selected),
            compression_ratio=round(len(selected) / max(total, 1), 2),
        )
        logger.info(f"EvidenceSelection: {total} candidates -> {len(selected)} items.")
        return {
            "evidence_package": package,
            "agent_traces": [trace("evidence_selection", "completed",
                                   f"{total} candidates -> {len(selected)} items "
                                   f"({min(len(chunk_items), MAX_CHUNKS)} passages, {min(len(triple_items), MAX_TRIPLES)} relations)",
                                   started)],
        }
