"""
Hybrid Retrieval Agent Node for LangGraph.
Executes dense vector + BM25 full-text search on LanceDB for the main query and up to a few
decomposed sub-questions / expansion variants, fuses the result lists with Reciprocal Rank
Fusion, and reranks the pool with the neural cross-encoder.
"""
import time
import logging
from typing import Dict, Any, List, Optional, Tuple

from core.state import AgentWorkflowState, RetrievedChunk
from retrieval.embeddings import EmbeddingService
from retrieval.lancedb_store import LanceDBStore, rrf_fuse
from retrieval.reranker import ChunkReranker
from agents.llm_utils import trace

logger = logging.getLogger("OmniDoc.HybridAgent")

MAX_EXTRA_QUERIES = 3
CANDIDATES_PER_QUERY = 10
POOL_SIZE = 24
FINAL_TOP_K = 6
# Selected documents this short are read whole, so an overview ("what are the stages?") misses nothing.
WHOLE_DOCUMENT_CHUNKS = 10


def _norm(q: str) -> str:
    return " ".join((q or "").lower().split())


class HybridRetrievalAgent:
    """Retrieves and reranks document chunks using dense + lexical search."""

    def __init__(
        self,
        embed_service: EmbeddingService,
        lance_store: LanceDBStore,
        reranker: ChunkReranker
    ):
        self.embed_service = embed_service
        self.lance_store = lance_store
        self.reranker = reranker or ChunkReranker()

    def _queries(self, state: AgentWorkflowState) -> List[str]:
        semantic_q = state.get("semantic_query")
        intent = state.get("intent")
        main = (getattr(semantic_q, "resolved_query", None) or getattr(intent, "refined_query", None)
                or state.get("user_query", "")).strip()
        extras: List[str] = []
        if semantic_q is not None:
            extras.extend(getattr(semantic_q, "sub_questions", None) or [])
            variants = (getattr(semantic_q, "constraints", None) or {}).get("retrieval_variants") or []
            extras.extend(v for v in variants if isinstance(v, str))
        queries, seen = [main], {_norm(main)}
        for q in extras:
            if not isinstance(q, str) or not q.strip() or _norm(q) in seen:
                continue
            seen.add(_norm(q))
            queries.append(q.strip())
            if len(queries) > MAX_EXTRA_QUERIES:
                break
        return queries

    def search(self, queries: List[str], doc_ids: Optional[List[str]] = None, top_k: int = FINAL_TOP_K,
               candidates_per_query: int = CANDIDATES_PER_QUERY) -> Tuple[List[RetrievedChunk], int]:
        """
        Hybrid search for several phrasings of one need: each query runs dense + BM25 over
        the given documents, the lists are fused with RRF, and the pool is reranked with the
        cross-encoder (each passage keeps its best score over the queries). Returns the top
        passages and the size of the candidate pool.
        """
        queries = [q for q in queries if q and q.strip()]
        if not queries:
            return [], 0
        rankings: List[List[str]] = []
        pool: Dict[str, RetrievedChunk] = {}
        try:
            vectors = self.embed_service.embed_queries(queries)
        except Exception as e:
            logger.warning(f"Query embedding failed ({e}); lexical search only.")
            vectors = [[] for _ in queries]

        for q, vec in zip(queries, vectors):
            try:
                hits = self.lance_store.hybrid_search(query=q, query_vector=vec, top_k=candidates_per_query,
                                                      doc_ids=doc_ids or None)
            except Exception as e:
                logger.warning(f"Hybrid search failed for '{q[:60]}': {e}")
                hits = []
            rankings.append([h.chunk_id for h in hits])
            for h in hits:
                pool.setdefault(h.chunk_id, h)
        if not pool:
            return [], 0

        fused = rrf_fuse(rankings)
        candidates = [pool[c] for c in sorted(fused, key=lambda c: fused[c], reverse=True)[:POOL_SIZE]]

        # Rerank: each passage keeps its best relevance over the main query and sub-queries,
        # so comparison questions do not lose the passages about the second entity.
        texts = [c.text for c in candidates]
        best = [0.0] * len(candidates)
        for q in queries:
            for i, score in enumerate(self.reranker.score_pairs(q, texts)):
                best[i] = max(best[i], float(score))
        method = "neural_reranked" if getattr(self.reranker, "is_neural", False) else "lexical_reranked"
        scored = [c.model_copy(update={"score": round(score, 4), "retrieval_method": method})
                  for c, score in zip(candidates, best)]
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k], len(pool)

    @staticmethod
    def _covered(question: str, passages: List[RetrievedChunk]) -> bool:
        """Whether the passages mention most of the content words of a sub-question."""
        from agents.understanding_agent import content_words
        words = {w.lower() for w in content_words(question)}
        if not words:
            return True
        text = " ".join(p.text.lower() for p in passages)
        return sum(1 for w in words if w in text) >= 0.6 * len(words)

    def _whole_documents(self, doc_ids: List[str], have: set) -> List[RetrievedChunk]:
        """
        The other passages of the selected documents (or of the whole library when nothing is
        selected) when together they have <= WHOLE_DOCUMENT_CHUNKS.
        """
        if not doc_ids:
            if self.lance_store.count_chunks() > WHOLE_DOCUMENT_CHUNKS:
                return []
            doc_ids = self.lance_store.document_ids()
        if not doc_ids or len(doc_ids) > WHOLE_DOCUMENT_CHUNKS:
            return []
        total = 0
        for d in doc_ids:
            total += self.lance_store.count_document_chunks(d, WHOLE_DOCUMENT_CHUNKS + 1)
            if total > WHOLE_DOCUMENT_CHUNKS:
                return []
        return [c.model_copy(update={"retrieval_method": "whole_document"})
                for d in doc_ids for c in self.lance_store.get_document_chunks(d) if c.chunk_id not in have]

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Executes hybrid retrieval over the active documents (all documents if none selected),
        then a second, targeted search for each part of the question the passages do not
        cover yet (no model call).
        """
        started = time.perf_counter()
        doc_ids = [d for d in (state.get("document_ids") or []) if d]
        queries = self._queries(state)
        logger.info(f"HybridRetrievalAgent searching {len(queries)} queries across docs: {doc_ids or 'ALL'}")
        top, pool_size = self.search(queries, doc_ids or None)
        semantic_q = state.get("semantic_query")
        subs = [q for q in (getattr(semantic_q, "sub_questions", None) or []) if isinstance(q, str) and q.strip()]
        second = 0
        if top and len(subs) > 1:
            have = {c.chunk_id for c in top}
            for sub in subs[:4]:
                if self._covered(sub, top):
                    continue
                extra, _ = self.search([sub], doc_ids or None, top_k=2)
                for ch in extra:
                    if ch.chunk_id not in have:
                        have.add(ch.chunk_id)
                        top.append(ch)
                        second += 1
        whole = self._whole_documents(doc_ids, {c.chunk_id for c in top})
        top.extend(whole)
        if not top:
            return {
                "chunk_context": [],
                "agent_traces": [trace("hybrid_retrieval", "completed", "No passages matched.", started,
                                       queries=queries)],
            }
        detail = f"{pool_size} candidates from {len(queries)} queries -> {len(top)} reranked passages"
        if second:
            detail += f" ({second} from a second search for uncovered parts)"
        if whole:
            detail += f" (+{len(whole)} so the short document is read whole)"
        return {
            "chunk_context": [ch.model_dump() for ch in top],
            "agent_traces": [trace("hybrid_retrieval", "completed", detail, started, queries=queries)],
        }
