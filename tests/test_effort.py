"""The effort level chosen in the app decides how much evidence a question reads."""
from core import effort
from agents import evidence_selection_agent as esa
from agents.evidence_selection_agent import EvidenceSelectionAgent


class OrderedReranker:
    """Scores passages in the order given, so the test controls which ones rank first."""

    def score_pairs(self, query, texts):
        return [1.0 - i / 100 for i in range(len(texts))]


def _chunks(n):
    return [
        {
            "chunk_id": f"c{i}", "doc_id": "d1", "page_number": i + 1, "score": 0.5,
            "text": f"Passage {i} about revenue in year {2000 + i}, with its own distinct wording number {i * 7}.",
            "retrieval_method": "hybrid",
        }
        for i in range(n)
    ]


def _selected(level):
    state = {"user_query": "How did revenue change?", "chunk_context": _chunks(24), "graph_context": [],
             "needs": {"web_mode": "auto", "effort": level}}
    out = EvidenceSelectionAgent(reranker=OrderedReranker()).run(state)
    return out["evidence_package"].selected_count


def test_levels_are_cleaned():
    assert effort.clean("quick") == "quick"
    assert effort.clean("thorough") == "thorough"
    assert effort.clean("everything") == "balanced"
    assert effort.clean(None) == "balanced"
    assert effort.level({}) == "balanced"
    assert effort.level({"needs": {"effort": "quick"}}) == "quick"


def test_scaled_picks_the_count_for_the_level():
    assert effort.scaled({"needs": {"effort": "quick"}}, 10, quick=6, thorough=16) == 6
    assert effort.scaled({"needs": {}}, 10, quick=6, thorough=16) == 10
    assert effort.scaled({"needs": {"effort": "thorough"}}, 10, quick=6, thorough=16) == 16


def test_evidence_selection_reads_more_with_more_effort():
    quick, balanced, thorough = _selected("quick"), _selected("balanced"), _selected("thorough")
    assert quick == min(6, esa.MAX_CHUNKS)
    assert balanced == esa.MAX_CHUNKS
    assert thorough == max(16, esa.MAX_CHUNKS)
    assert quick < balanced < thorough or esa.MAX_CHUNKS >= 16


def test_query_request_accepts_only_known_levels():
    from pydantic import ValidationError
    import pytest
    from server import QueryRequest

    assert QueryRequest(query="q").effort == "balanced"
    assert QueryRequest(query="q", effort="thorough").effort == "thorough"
    with pytest.raises(ValidationError):
        QueryRequest(query="q", effort="maximum")
