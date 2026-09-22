"""
Neural Cross-Encoder Reranker for OmniDoc.
Refines candidate chunks from hybrid search to maximize NDCG and eliminate distractor noise.
"""
import logging
from typing import List, Tuple
from core.state import RetrievedChunk

logger = logging.getLogger("OmniDoc.Reranker")


class ChunkReranker:
    """Reranks candidate chunks using a cross-encoder model."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.model_name = model_name
        self.model = None
        self._init_model()

    def _init_model(self):
        """Attempts to load CrossEncoder with graceful fallback."""
        try:
            from sentence_transformers import CrossEncoder
            # Load cross-encoder if available
            self.model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            logger.info("CrossEncoder model initialized successfully.")
        except Exception as e:
            logger.info(f"CrossEncoder offline/not loaded ({e}). Using lexical-density heuristic reranker.")

    def rerank(self, query: str, chunks: List[RetrievedChunk], top_k: int = 5) -> List[RetrievedChunk]:
        """
        Reranks chunks based on joint query-passage cross-attention scores.
        """
        if not chunks:
            return []

        if len(chunks) <= top_k and not self.model:
            return chunks

        if self.model:
            try:
                pairs = [(query, ch.text) for ch in chunks]
                scores = self.model.predict(pairs)
                
                scored_chunks: List[Tuple[float, RetrievedChunk]] = []
                for score, ch in zip(scores, chunks):
                    ch.score = float(score)
                    ch.retrieval_method = "neural_reranked"
                    scored_chunks.append((float(score), ch))

                scored_chunks.sort(key=lambda x: x[0], reverse=True)
                return [ch for _, ch in scored_chunks[:top_k]]
            except Exception as e:
                logger.warning(f"Cross-encoder inference failed: {e}. Falling back to baseline.")

        # Heuristic fallback: term-frequency density boost
        query_terms = set(query.lower().split())
        scored_chunks = []
        for ch in chunks:
            text_terms = ch.text.lower().split()
            overlap = sum(1 for t in text_terms if t in query_terms)
            density = overlap / (len(text_terms) + 1e-5)
            adjusted_score = ch.score * 0.7 + density * 0.3
            ch.score = adjusted_score
            scored_chunks.append((adjusted_score, ch))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        return [ch for _, ch in scored_chunks[:top_k]]
