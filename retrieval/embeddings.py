"""
Unified Embedding Service for OmniDoc.
Ollama embeddings (nomic-embed-text by default) with batched requests and disk caching.
"""
import os
import pickle
import hashlib
import logging
from typing import List, Optional

import ollama

logger = logging.getLogger("OmniDoc.Embeddings")

_EMBED_BATCH = 32


class EmbeddingService:
    """Computes dense vector representations with caching."""

    def __init__(self, model_name: str = "nomic-embed-text", cache_dir: str = ".cache/embeddings"):
        self.model_name = model_name
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self.dimension = 768  # nomic-embed-text is 768, bge-m3 is 1024
        self._client = ollama.Client(timeout=float(os.getenv("OMNIDOC_EMBED_TIMEOUT", "120")))

    def _hash_text(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _cache_path(self, text: str) -> str:
        return os.path.join(self.cache_dir, f"{self._hash_text(text)}.pkl")

    def _read_cache(self, text: str) -> Optional[List[float]]:
        path = self._cache_path(text)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                emb = pickle.load(f)
            return emb if isinstance(emb, list) and emb else None
        except Exception:
            return None

    def _write_cache(self, text: str, emb: List[float]) -> None:
        try:
            with open(self._cache_path(text), "wb") as f:
                pickle.dump(emb, f)
        except Exception as e:
            logger.debug(f"Embedding cache write skipped: {e}")

    def _embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """One batched request; falls back to per-text requests if the batch call fails."""
        try:
            resp = self._client.embed(model=self.model_name, input=texts)
            embs = [list(map(float, e)) for e in resp["embeddings"]]
            if len(embs) == len(texts):
                return embs
        except Exception as e:
            logger.warning(f"Batch embedding failed ({e}); retrying per text.")
        out: List[Optional[List[float]]] = []
        for t in texts:
            try:
                resp = self._client.embeddings(model=self.model_name, prompt=t)
                emb = resp["embedding"]
                out.append(list(map(float, emb)) if emb else None)
            except Exception as e:
                logger.error(f"Failed to embed text: {e}")
                out.append(None)
        return out

    def embed_query(self, query: str) -> List[float]:
        """Embeds a single search query (a zero vector means the embedding failed)."""
        res = self.embed_texts([query])
        return res[0] if res else [0.0] * self.dimension

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embeds a batch of texts using Ollama with disk caching."""
        embeddings: List[Optional[List[float]]] = []
        uncached: List[int] = []
        for i, text in enumerate(texts):
            cached = self._read_cache(text)
            embeddings.append(cached)
            if cached is None:
                uncached.append(i)

        if uncached:
            logger.info(f"Computing embeddings for {len(uncached)} uncached texts...")
            for start in range(0, len(uncached), _EMBED_BATCH):
                idxs = uncached[start:start + _EMBED_BATCH]
                batch = [texts[i] if texts[i].strip() else " " for i in idxs]
                for i, emb in zip(idxs, self._embed_batch(batch)):
                    if emb:
                        self.dimension = len(emb)
                        embeddings[i] = emb
                        self._write_cache(texts[i], emb)

        failed = [i for i, e in enumerate(embeddings) if not e]
        if failed:
            logger.error(f"{len(failed)} text(s) could not be embedded; storing zero vectors (lexical search only).")
        return [e if e else [0.0] * self.dimension for e in embeddings]
