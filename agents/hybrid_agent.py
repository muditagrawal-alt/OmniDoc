"""
Hybrid Retrieval Agent Node for LangGraph.
Executes dense vector + BM25 full-text search on LanceDB for the main query and up to a few
decomposed sub-questions / expansion variants, fuses the result lists with Reciprocal Rank
Fusion, and reranks the pool with the neural cross-encoder.
"""
import time
import logging
from typing import Dict, Any, List

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

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Executes hybrid retrieval over the active documents (all documents if none selected).
        """
        started = time.perf_counter()
        doc_ids = [d for d in (state.get("document_ids") or []) if d]
        queries = self._queries(state)
        logger.info(f"HybridRetrievalAgent searching {len(queries)} queries across docs: {doc_ids or 'ALL'}")

        rankings: List[List[str]] = []
        pool: Dict[str, RetrievedChunk] = {}
        try:
            vectors = self.embed_service.embed_texts(queries)
        except Exception as e:
            logger.warning(f"Query embedding failed ({e}); lexical search only.")
            vectors = [[] for _ in queries]

        for q, vec in zip(queries, vectors):
            try:
                hits = self.lance_store.hybrid_search(query=q, query_vector=vec, top_k=CANDIDATES_PER_QUERY,
                                                      doc_ids=doc_ids or None)
            except Exception as e:
                logger.warning(f"Hybrid search failed for '{q[:60]}': {e}")
                hits = []
            rankings.append([h.chunk_id for h in hits])
            for h in hits:
                pool.setdefault(h.chunk_id, h)

        if not pool:
            return {
                "chunk_context": [],
                "agent_traces": [trace("hybrid_retrieval", "completed", "No passages matched.", started,
                                       queries=queries)],
            }

        fused = rrf_fuse(rankings)
        candidates = [pool[c] for c in sorted(fused, key=lambda c: fused[c], reverse=True)[:POOL_SIZE]]

        # Rerank: each passage keeps its best relevance over the main query and sub-queries,
        # so comparison questions do not lose the passages about the second entity.
        texts = [c.text for c in candidates]
        best = [0.0] * len(candidates)
        for q in queries:
            for i, s in enumerate(self.reranker.score_pairs(q, texts)):
                best[i] = max(best[i], float(s))
        method = "neural_reranked" if getattr(self.reranker, "is_neural", False) else "lexical_reranked"
        scored = [c.model_copy(update={"score": round(s, 4), "retrieval_method": method})
                  for c, s in zip(candidates, best)]
        scored.sort(key=lambda c: c.score, reverse=True)
        top = scored[:FINAL_TOP_K]

        return {
            "chunk_context": [ch.model_dump() for ch in top],
            "agent_traces": [trace("hybrid_retrieval", "completed",
                                   f"{len(pool)} candidates from {len(queries)} queries -> {len(top)} reranked passages",
                                   started, queries=queries)],
        }
