"""
Unified Embedding Service for OmniDoc.
Supports BGE-M3 and Ollama embeddings with disk caching.
"""
import os
import pickle
import hashlib
import logging
from typing import List
import numpy as np
import ollama

logger = logging.getLogger("OmniDoc.Embeddings")


class EmbeddingService:
    """Computes dense vector representations with caching."""

    def __init__(self, model_name: str = "nomic-embed-text", cache_dir: str = ".cache/embeddings"):
        self.model_name = model_name
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self.dimension = 768  # nomic-embed-text is 768, bge-m3 is 1024

    def _hash_text(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def embed_query(self, query: str) -> List[float]:
        """Embeds a single search query."""
        res = self.embed_texts([query])
        return res[0] if res else [0.0] * self.dimension

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embeds a batch of texts using Ollama with disk caching."""
        embeddings = []
        uncached_indices = []
        uncached_texts = []

        for i, text in enumerate(texts):
            h = self._hash_text(text)
            cache_path = os.path.join(self.cache_dir, f"{h}.pkl")
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "rb") as f:
                        embeddings.append(pickle.load(f))
                    continue
                except Exception:
                    pass
            embeddings.append(None)
            uncached_indices.append(i)
            uncached_texts.append(text)

        if uncached_texts:
            logger.info(f"Computing embeddings for {len(uncached_texts)} uncached chunks...")
            for idx, text in zip(uncached_indices, uncached_texts):
                try:
                    resp = ollama.embeddings(model=self.model_name, prompt=text)
                    emb = resp.get("embedding", [])
                    if not emb:
                        emb = [0.0] * self.dimension
                    else:
                        self.dimension = len(emb)
                    
                    embeddings[idx] = emb
                    # Cache to disk
                    h = self._hash_text(text)
                    with open(os.path.join(self.cache_dir, f"{h}.pkl"), "wb") as f:
                        pickle.dump(emb, f)
                except Exception as e:
                    logger.error(f"Failed to embed text: {e}")
                    embeddings[idx] = [0.0] * self.dimension

        return embeddings
