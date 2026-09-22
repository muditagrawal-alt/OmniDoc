"""
Hybrid Retrieval Agent Node for LangGraph.
Executes dense vector + BM25 full-text search on LanceDB,
followed by neural cross-encoder reranking.
"""
import logging
from typing import Dict, Any, List
from core.state import AgentWorkflowState, RetrievedChunk
from retrieval.embeddings import EmbeddingService
from retrieval.lancedb_store import LanceDBStore
from retrieval.reranker import ChunkReranker

logger = logging.getLogger("OmniDoc.HybridAgent")


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
        self.reranker = reranker

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Executes hybrid retrieval over the active documents.
        """
        intent = state.get("intent")
        search_query = intent.refined_query if intent else state.get("user_query", "")
        doc_ids = state.get("document_ids", [])

        logger.info(f"HybridRetrievalAgent searching for: '{search_query[:60]}' across docs: {doc_ids}")
        
        # Compute dense vector
        query_vec = self.embed_service.embed_query(search_query)

        # LanceDB hybrid search (Vector + BM25 FTS)
        candidates = self.lance_store.hybrid_search(
            query=search_query,
            query_vector=query_vec,
            top_k=8,
            doc_ids=doc_ids if doc_ids else None
        )

        # Neural reranker
        reranked = self.reranker.rerank(query=search_query, chunks=candidates, top_k=5)

        serialized_chunks = [ch.model_dump() for ch in reranked]
        return {"chunk_context": serialized_chunks}
