"""
Unified Embedding Service for OmniDoc.

The embedding model is a spec, like the chat models:

    "nomic-embed-text"                 local Ollama model (the default when Ollama runs)
    "st:intfloat/multilingual-e5-small"  local sentence-transformers model on the CPU (no Ollama
                                       needed; multilingual, used in deployments without Ollama)
    "gemini:gemini-embedding-001"      hosted, free tier (also "jina:...", "mistral:...")

Embeddings are batched and cached on disk; the cache key includes the model, so switching
models never mixes vectors. Queries and passages are embedded differently where the model
expects it (E5 "query:" / "passage:" prefixes).
"""
import os
import pickle
import hashlib
import logging
import threading
from typing import Any, List, Optional

logger = logging.getLogger("OmniDoc.Embeddings")

_EMBED_BATCH = 32
LOCAL_FALLBACK = "st:intfloat/multilingual-e5-small"


def default_embed_model() -> str:
    """OMNIDOC_EMBED_MODEL, else local Ollama's nomic-embed-text, else a hosted free model, else a local CPU model."""
    explicit = os.getenv("OMNIDOC_EMBED_MODEL", "").strip()
    if explicit:
        return explicit
    from agents.llm_utils import ollama_reachable
    if ollama_reachable():
        return "nomic-embed-text"
    from agents.llm_providers import REGISTRY
    for name in ("gemini", "jina", "mistral"):
        p = REGISTRY[name]
        if p.configured and p.embed_model:
            return f"{name}:{p.embed_model}"
    return LOCAL_FALLBACK


class EmbeddingService:
    """Computes dense vector representations with caching."""

    def __init__(self, model_name: Optional[str] = None, cache_dir: str = ".cache/embeddings"):
        self.model_name = model_name or default_embed_model()
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self.dimension = 768
        self._ollama = None
        self._st = None
        self._st_lock = threading.Lock()
        logger.info(f"Embedding model: {self.model_name}")

    # ----------------------------------------------------------------- backends
    @property
    def kind(self) -> str:
        from agents.llm_providers import parse_spec
        if self.model_name.startswith("st:"):
            return "st"
        return parse_spec(self.model_name)[0]

    def _prefix(self, text: str, kind: str) -> str:
        if "e5" in self.model_name.lower():
            return ("query: " if kind == "query" else "passage: ") + text
        return text

    def _embed_st(self, texts: List[str], kind: str) -> List[Optional[List[float]]]:
        with self._st_lock:
            if self._st is None:
                from sentence_transformers import SentenceTransformer
                self._st = SentenceTransformer(self.model_name[3:], device="cpu")
        vectors = self._st.encode([self._prefix(t, kind) for t in texts], batch_size=16, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]

    def _embed_ollama(self, texts: List[str]) -> List[Optional[List[float]]]:
        import ollama
        from agents.llm_providers import parse_spec
        if self._ollama is None:
            self._ollama = ollama.Client(timeout=float(os.getenv("OMNIDOC_EMBED_TIMEOUT", "120")))
        name = parse_spec(self.model_name)[1]
        try:
            resp = self._ollama.embed(model=name, input=texts)
            embs = [list(map(float, e)) for e in resp["embeddings"]]
            if len(embs) == len(texts):
                return embs
        except Exception as e:
            logger.warning(f"Batch embedding failed ({e}); retrying per text.")
        out: List[Optional[List[float]]] = []
        for t in texts:
            try:
                emb = self._ollama.embeddings(model=name, prompt=t)["embedding"]
                out.append(list(map(float, emb)) if emb else None)
            except Exception as e:
                logger.warning(f"Failed to embed text: {e}")
                out.append(None)
        return out

    def _embed_remote(self, texts: List[str], kind: str) -> List[Optional[List[float]]]:
        backend = self.kind
        if backend == "st":
            return self._embed_st(texts, kind)
        if backend == "ollama":
            return self._embed_ollama(texts)
        from agents.llm_providers import REGISTRY, parse_spec, openai_embed
        provider, name = parse_spec(self.model_name)
        p = REGISTRY[provider]
        return openai_embed(p, name or p.embed_model, [self._prefix(t, kind) for t in texts])

    # -------------------------------------------------------------------- cache
    def _key(self, text: str, kind: str) -> str:
        material = f"{self.model_name}\x00{kind if 'e5' in self.model_name.lower() else ''}\x00{text}"
        return hashlib.md5(material.encode("utf-8"), usedforsecurity=False).hexdigest()  # cache file name only

    def _read_cache(self, key: str) -> Optional[List[float]]:
        path = os.path.join(self.cache_dir, f"{key}.pkl")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                emb = pickle.load(f)
            return emb if isinstance(emb, list) and emb else None
        except Exception:
            return None

    def _write_cache(self, key: str, emb: List[float]) -> None:
        try:
            with open(os.path.join(self.cache_dir, f"{key}.pkl"), "wb") as f:
                pickle.dump(emb, f)
        except Exception as e:
            logger.debug(f"Embedding cache write skipped: {e}")

    # ---------------------------------------------------------------------- API
    def embed_query(self, query: str) -> List[float]:
        """Embeds a single search query (a zero vector means the embedding failed)."""
        res = self.embed_texts([query], kind="query")
        return res[0] if res else [0.0] * self.dimension

    def embed_queries(self, queries: List[str]) -> List[List[float]]:
        return self.embed_texts(queries, kind="query")

    def _compute(self, texts: List[str], keys: List[str], embeddings: List[Optional[List[float]]],
                 missing: List[int], kind: str) -> None:
        logger.info(f"Computing embeddings for {len(missing)} uncached texts with {self.model_name}...")
        for start in range(0, len(missing), _EMBED_BATCH):
            idxs = missing[start:start + _EMBED_BATCH]
            batch = [texts[i] if texts[i].strip() else " " for i in idxs]
            try:
                vectors = self._embed_remote(batch, kind)
            except Exception as e:
                logger.error(f"Embedding failed with {self.model_name}: {e}")
                vectors = [None] * len(batch)
            for i, emb in zip(idxs, vectors):
                if emb:
                    self.dimension = len(emb)
                    embeddings[i] = emb
                    self._write_cache(keys[i], emb)

    def embed_texts(self, texts: List[str], kind: str = "passage") -> List[List[float]]:
        """Embeds a batch of texts with disk caching (failed texts get zero vectors: lexical search only)."""
        keys = [self._key(t, kind) for t in texts]
        embeddings: List[Optional[List[float]]] = [self._read_cache(k) for k in keys]
        for e in embeddings:
            if e:
                self.dimension = len(e)
        missing = [i for i, e in enumerate(embeddings) if e is None]
        if missing:
            self._compute(texts, keys, embeddings, missing, kind)
        failed = sum(1 for e in embeddings if not e)
        if failed:
            logger.error(f"{failed} text(s) could not be embedded; storing zero vectors (lexical search only).")
        return [e if e else [0.0] * self.dimension for e in embeddings]
