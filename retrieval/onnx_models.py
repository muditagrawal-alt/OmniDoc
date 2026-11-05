"""
Small ONNX models for servers without PyTorch (the slim image for 1 GB hosts): a sentence embedder
and a cross-encoder, run with ONNX Runtime and Hugging Face tokenizers.

Memory is the constraint these are tuned for. ONNX Runtime normally keeps a memory arena at its
peak; here the arena and memory patterns are off and batches are small (two passages of up to
512 tokens per embedding call: batches of eight added 270 MB of activations, two add 50), so the
int8 bge-small embedder and the int8 MiniLM cross-encoder together stay near 370 MB after use
(measured; the PyTorch versions need about 1.2 GB). Models download once from Hugging Face into
OMNIDOC_ONNX_CACHE (the slim image ships them).

Model ids are Hugging Face repositories with an ONNX export. Known ones carry their file and pooling;
any other repository is tried with onnx/model_quantized.onnx and mean pooling.
"""
import os
import logging
import threading
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("OmniDoc.Onnx")

MODELS: Dict[str, Dict[str, str]] = {
    # English, 33M parameters: about 180 MB loaded (multilingual models carry a 250k-word vocabulary
    # that ONNX Runtime expands to roughly 700 MB, too much for a 1 GB server).
    "Xenova/bge-small-en-v1.5": {"file": "onnx/model_quantized.onnx", "pooling": "cls"},
    "Xenova/multilingual-e5-small": {"file": "onnx/model_quantized.onnx", "pooling": "mean"},
    "Xenova/ms-marco-MiniLM-L-6-v2": {"file": "onnx/model_quantized.onnx"},
}
EMBED_BATCH = int(os.getenv("OMNIDOC_ONNX_BATCH", "2"))
RERANK_BATCH = 8  # (query, passage) pairs are shorter than whole passages
MAX_TOKENS = 512
_lock = threading.Lock()


def cache_dir() -> str:
    return os.getenv("OMNIDOC_ONNX_CACHE") or os.path.join(
        os.getenv("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface"), "onnx")


def threads() -> int:
    """OMNIDOC_ONNX_THREADS: set it to the container's CPUs (ONNX Runtime would count the host's cores)."""
    return int(os.getenv("OMNIDOC_ONNX_THREADS", "0") or 0)


def _files(repo: str) -> Tuple[str, str]:
    from huggingface_hub import hf_hub_download
    spec = MODELS.get(repo, {})
    model = hf_hub_download(repo, spec.get("file", "onnx/model_quantized.onnx"), cache_dir=cache_dir())
    tokenizer = hf_hub_download(repo, "tokenizer.json", cache_dir=cache_dir())
    return model, tokenizer


def _session(path: str):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads()
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
    return ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])


def _tokenizer(path: str):
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(path)
    tok.enable_truncation(MAX_TOKENS)
    tok.enable_padding()
    return tok


class _Model:
    def __init__(self, repo: str):
        model_path, tokenizer_path = _files(repo)
        self.repo = repo
        self.session = _session(model_path)
        self.tokenizer = _tokenizer(tokenizer_path)
        self.inputs = {i.name for i in self.session.get_inputs()}

    def _run(self, encodings) -> "object":
        import numpy as np
        feeds = {"input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
                 "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64)}
        if "token_type_ids" in self.inputs:
            feeds["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)
        return self.session.run(None, feeds)[0], feeds["attention_mask"]


class OnnxEmbedder(_Model):
    """Normalized sentence vectors (CLS or mean pooling, as the model was trained)."""

    def __init__(self, repo: str):
        super().__init__(repo)
        self.pooling = MODELS.get(repo, {}).get("pooling", "mean")

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        import numpy as np
        out: List[List[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            hidden, mask = self._run(self.tokenizer.encode_batch(list(texts[start:start + EMBED_BATCH])))
            if self.pooling == "cls":
                pooled = hidden[:, 0]
            else:
                weights = mask[..., None].astype(hidden.dtype)
                pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
            pooled = pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
            out.extend(v.astype(float).tolist() for v in pooled)
        return out


class OnnxCrossEncoder(_Model):
    """CrossEncoder.predict() for (query, passage) pairs: raw relevance logits, like the ms-marco models."""

    def predict(self, pairs: Sequence[Tuple[str, str]], show_progress_bar: bool = False) -> List[float]:
        scores: List[float] = []
        for start in range(0, len(pairs), RERANK_BATCH):
            logits, _ = self._run(self.tokenizer.encode_batch([(q, t or "") for q, t in pairs[start:start + RERANK_BATCH]]))
            scores.extend(float(row[0]) for row in logits)
        return scores

    def to(self, _device: str) -> "OnnxCrossEncoder":
        return self


_loaded: Dict[Tuple[str, str], object] = {}


def load(kind: str, repo: str):
    """The process-wide embedder ("embed") or cross-encoder ("rerank") for a repository."""
    key = (kind, repo)
    with _lock:
        if key not in _loaded:
            _loaded[key] = OnnxEmbedder(repo) if kind == "embed" else OnnxCrossEncoder(repo)
            logger.info(f"ONNX {'embedding model' if kind == 'embed' else 'cross-encoder'} {repo} loaded.")
        return _loaded[key]


def warm(repos: Optional[List[Tuple[str, str]]] = None) -> None:
    """Downloads the models ahead of time (used when building the slim image)."""
    for kind, repo in repos or [("embed", "Xenova/bge-small-en-v1.5"), ("rerank", "Xenova/ms-marco-MiniLM-L-6-v2")]:
        _files(repo)
        print(f"cached {repo}")
