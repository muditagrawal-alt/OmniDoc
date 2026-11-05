"""
The slim build's local models (retrieval/onnx_models.py): int8 ONNX embedding and cross-encoder
models on ONNX Runtime, used when PyTorch is not installed. The model tests download about 60 MB
from Hugging Face once and are skipped when that is not possible.
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from core import memory  # noqa: E402


def _model(kind, repo):
    pytest.importorskip("onnxruntime")
    pytest.importorskip("tokenizers")
    from retrieval import onnx_models
    try:
        return onnx_models.load(kind, repo)
    except Exception as e:  # offline, or Hugging Face unreachable
        pytest.skip(f"model not available: {e}")


def test_the_onnx_embedder_puts_the_relevant_passage_closest():
    model = _model("embed", "Xenova/bge-small-en-v1.5")
    from retrieval.embeddings import EmbeddingService
    service = EmbeddingService.__new__(EmbeddingService)
    service.model_name = "onnx:Xenova/bge-small-en-v1.5"
    query, relevant, other = model.embed([
        service._prefix("How much did revenue grow in 2023?", "query"),
        "Revenue grew 12% to $4.2 billion in fiscal 2023, driven by services.",
        "The board met four times and approved the dividend policy.",
    ])
    assert len(query) == 384 and abs(sum(v * v for v in query) - 1) < 1e-3  # normalized
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert dot(query, relevant) > dot(query, other) + 0.1


def test_the_onnx_cross_encoder_scores_like_the_pytorch_one():
    model = _model("rerank", "Xenova/ms-marco-MiniLM-L-6-v2")
    relevant, other = model.predict([
        ("How much did revenue grow?", "Revenue grew 12% to $4.2 billion in fiscal 2023."),
        ("How much did revenue grow?", "The capital of India is New Delhi."),
    ])
    assert relevant > 3 and other < -5  # raw logits, as the PyTorch cross-encoder returns them


def test_without_pytorch_the_local_defaults_are_onnx(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "sentence_transformers" else real(name, *a))
    monkeypatch.delenv("OMNIDOC_RERANKER_MODEL", raising=False)
    from retrieval import embeddings, reranker
    try:
        assert importlib.reload(embeddings).LOCAL_FALLBACK == "onnx:Xenova/bge-small-en-v1.5"
        assert importlib.reload(reranker).DEFAULT_RERANKER_MODEL == "onnx:Xenova/ms-marco-MiniLM-L-6-v2"
    finally:
        monkeypatch.undo()
        importlib.reload(embeddings)
        importlib.reload(reranker)


def test_releasing_memory_is_safe_to_call_any_time():
    memory.release()
    memory.release()
    assert memory.rss_mb() > 0
