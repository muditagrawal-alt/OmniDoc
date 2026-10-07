"""
Neural Cross-Encoder Reranker for OmniDoc.
Refines candidate chunks from hybrid search to maximize NDCG and eliminate distractor noise.

The cross-encoder is loaded once per process (module-level cache) no matter how many
ChunkReranker instances are created. Scores are calibrated relevance probabilities in
[0, 1] (sigmoid of the cross-encoder logit), so they can be shown to users and compared
across chunks and graph triples.
"""
import os
import re
import math
import logging
import threading
from typing import Dict, List, Optional, Sequence

from core.state import RetrievedChunk

logger = logging.getLogger("OmniDoc.Reranker")

DEFAULT_RERANKER_MODEL = os.getenv("OMNIDOC_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

_MODEL_CACHE: Dict[str, object] = {}
_FAILED_MODELS: Dict[str, str] = {}
_CACHE_LOCK = threading.Lock()

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "is", "are", "was", "were", "be", "by",
    "with", "what", "which", "who", "whom", "how", "why", "when", "where", "does", "do", "did", "this",
    "that", "these", "those", "it", "its", "as", "at", "from", "about", "into", "than", "then",
}


def _load_cross_encoder(model_name: str):
    """Returns a cached CrossEncoder (or None if it cannot be loaded)."""
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]
    if model_name in _FAILED_MODELS:
        return None
    with _CACHE_LOCK:
        if model_name in _MODEL_CACHE:
            return _MODEL_CACHE[model_name]
        try:
            from sentence_transformers import CrossEncoder
            try:
                model = CrossEncoder(model_name, local_files_only=True)
            except Exception:
                model = CrossEncoder(model_name)
            _MODEL_CACHE[model_name] = model
            logger.info(f"CrossEncoder '{model_name}' loaded (cached for this process).")
            return model
        except Exception as e:
            _FAILED_MODELS[model_name] = str(e)
            logger.warning(f"CrossEncoder '{model_name}' unavailable ({e}). Using lexical-overlap reranker.")
            return None


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _terms(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


class ChunkReranker:
    """Reranks candidate chunks using a cross-encoder model."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or DEFAULT_RERANKER_MODEL
        self.model = _load_cross_encoder(self.model_name)
        act = None
        if self.model is not None:
            act = getattr(self.model, "activation_fn", None) or getattr(self.model, "default_activation_function", None)
        self._outputs_logits = act is None or type(act).__name__ == "Identity"

    @property
    def is_neural(self) -> bool:
        return self.model is not None

    def score_pairs(self, query: str, texts: Sequence[str]) -> List[float]:
        """Relevance in [0, 1] for each text (cross-encoder probability, or lexical overlap)."""
        if not texts:
            return []
        if self.model is not None:
            try:
                raw = self.model.predict([(query, t or "") for t in texts], show_progress_bar=False)
                vals = [float(v) for v in raw]
                # ms-marco cross-encoders output raw logits (Identity activation); map them
                # to probabilities so scores are comparable and bounded.
                if self._outputs_logits:
                    vals = [_sigmoid(v) for v in vals]
                return vals
            except Exception as e:
                logger.warning(f"Cross-encoder inference failed: {e}. Using lexical-overlap scores.")
        q_terms = set(_terms(query))
        if not q_terms:
            return [0.0 for _ in texts]
        out = []
        for t in texts:
            t_terms = set(_terms(t))
            out.append(len(q_terms & t_terms) / float(len(q_terms)))
        return out

    def rerank(self, query: str, chunks: List[RetrievedChunk], top_k: int = 5) -> List[RetrievedChunk]:
        """
        Reranks chunks by joint query-passage relevance; returns copies with ``score`` set to
        the reranker relevance and ``retrieval_method`` describing how it was scored.
        """
        if not chunks:
            return []
        scores = self.score_pairs(query, [ch.text for ch in chunks])
        method = "neural_reranked" if self.model is not None else "lexical_reranked"
        rescored = []
        for score, ch in zip(scores, chunks):
            rescored.append(ch.model_copy(update={"score": round(float(score), 4), "retrieval_method": method}))
        rescored.sort(key=lambda c: c.score, reverse=True)
        return rescored[:top_k]
