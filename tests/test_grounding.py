"""
Deterministic tests for evidence grounding: numbers, charts, calculations, citations,
verifier claims and figure selection. No model calls; runs in about a second.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from agents.llm_utils import number_in_text  # noqa: E402
from agents.visualization_agent import build_chart  # noqa: E402
from agents.math_agent import MathematicsAgent, UngroundedInputError  # noqa: E402
from agents.citations import normalize_citations, cited_numbers  # noqa: E402
from agents.vision_agent import VisionAgent  # noqa: E402
from guardrails.output_guard import _anchored, _content_words, stray_numbers  # noqa: E402

PLAN = (
    "Global power demand would be only 11.5 TW. Wind supplies 51 percent of the demand, provided by "
    "3.8 million large wind turbines. Another 40 percent comes from photovoltaics and concentrated solar "
    "plants, and about 9 percent from water-related methods. Only 17 to 20 percent of the energy in "
    "gasoline moves a vehicle. The plan needs 1,700,000,000 rooftop systems."
)


@pytest.mark.parametrize("value, expected", [
    (11.5, True),          # quoted as written
    (3800000, True),       # "3.8 million"
    (0.51, True),          # 51 percent as a fraction
    (1.7e9, True),         # thousands separators
    (11500, False),        # a magnitude word elsewhere in the text is not enough
    (17000000, False),     # 17 is a percentage, not 17 million
    (5.865, False),        # computed, never written
])
def test_number_in_text(value, expected):
    assert number_in_text(value, PLAN) is expected


def test_chart_merges_one_point_series_into_one_series():
    spec = {
        "chartable": True, "chart_type": "pie", "title": "Share of 11.5 TW", "y_label": "% of demand",
        "series": [
            {"name": "Wind", "points": [{"label": "Wind", "value": 51, "source": 1}]},
            {"name": "Solar", "points": [{"label": "photovoltaics and concentrated solar", "value": 40, "source": 1}]},
            {"name": "Water", "points": [{"label": "water-related methods", "value": 9, "source": 1}]},
        ],
    }
    art, reason = build_chart(spec, [{"n": 1, "_text": PLAN}])
    assert art is not None, reason
    trace = art["plotly_spec"]["data"][0]
    assert art["chart_type"] == "pie"
    assert trace["labels"] == ["Wind", "Solar", "Water"]
    assert trace["values"] == [51, 40, 9]
    assert art["source_ns"] == [1]


def test_chart_drops_values_missing_from_evidence():
    spec = {"chartable": True, "chart_type": "bar", "series": [{"name": "Plants", "points": [
        {"label": "Wind", "value": 51, "source": 1},
        {"label": "Geothermal", "value": 77, "source": 1},
    ]}]}
    art, reason = build_chart(spec, [{"n": 1, "_text": PLAN}])
    assert art is None
    assert "1 unverified" in reason


def test_math_rejects_unexplained_inputs():
    agent = MathematicsAgent()
    calc = {"task": "Wind output", "inputs": {"total_power": 12000, "wind_share": 0.51},
            "expression": "total_power * wind_share", "units": "TW", "assumptions": []}
    with pytest.raises(UngroundedInputError):
        agent._build_result(calc, "How many terawatts would wind supply?", PLAN, [])


def test_math_accepts_quoted_inputs():
    agent = MathematicsAgent()
    calc = {"task": "Wind output", "inputs": {"total_power": 11.5, "wind_share": 0.51},
            "expression": "total_power * wind_share", "units": "TW", "assumptions": []}
    res = agent._build_result(calc, "How many terawatts would wind supply?", PLAN, [])
    assert res is not None
    assert abs(float(res["exact_result"]) - 5.865) < 1e-9


def test_math_undoes_a_unit_scale_slip_against_the_quoted_unit():
    agent = MathematicsAgent()
    calc = {"task": "Wind output", "inputs": {"total_demand": 11500, "wind_share": 51},
            "expression": "wind_share / 100 * total_demand", "units": "TW", "assumptions": []}
    res = agent._build_result(calc, "How many terawatts would wind supply?", PLAN, [])
    assert res is not None
    assert abs(float(res["exact_result"]) - 5.865) < 1e-9
    assert any("11.5 TW as written" in a for a in res["assumptions"])


def test_math_does_not_rescale_into_a_different_unit():
    agent = MathematicsAgent()
    calc = {"task": "Wind share", "inputs": {"total_demand": 11500, "wind_share": 51},
            "expression": "wind_share / total_demand * 100", "units": "%", "assumptions": []}
    with pytest.raises(UngroundedInputError):
        agent._build_result(calc, "What share is wind?", PLAN, [])


def test_math_accepts_explained_derived_input():
    agent = MathematicsAgent()
    calc = {"task": "Average", "inputs": {"total_share": 100, "sources": 3},
            "expression": "total_share / sources", "units": "%",
            "assumptions": ["sources = 3 counts wind, solar and water"]}
    res = agent._build_result(calc, "Average share per source?", PLAN + " 100 percent", [])
    assert res is not None


def test_citations_drop_numbers_beyond_the_source_list():
    text = "Wind supplies 51% [1][2], solar 40% [7] and water 9% [1, 3]."
    out = normalize_citations(text, 3)
    assert "[7]" not in out
    assert cited_numbers(out) == [1, 2, 3]


def test_verifier_ignores_claims_taken_from_evidence():
    answer = "The figure compares renewable supply with demand in 2030 [7]."
    words = _content_words(answer)
    assert _anchored("The figure compares renewable supply with demand in 2030", words)
    assert not _anchored("The maximum power consumed worldwide is about 12.5 trillion watts", words)


def test_vision_prefers_the_page_the_retriever_found():
    with tempfile.TemporaryDirectory() as d:
        folder = os.path.join(d, "doc_a")
        os.makedirs(folder)
        for name in ("p4_page.png", "p9_img0.png", "p9_img1.png", "p1_img0.png"):
            open(os.path.join(folder, name), "wb").close()
        agent = VisionAgent(images_dir=d)
        figures = agent._candidate_figures({
            "document_ids": ["doc_a"],
            "chunk_context": [{"doc_id": "doc_a", "page_number": 4, "score": 0.9},
                              {"doc_id": "doc_a", "page_number": 9, "score": 0.1}],
        })
        assert [f["figure_id"] for f in figures[:3]] == ["doc_a_p4_page", "doc_a_p9_img0", "doc_a_p9_img1"]
        # Other documents' figures are never read.
        assert agent._candidate_figures({"document_ids": ["doc_b"], "chunk_context": []}) == []


def test_output_guard_flags_numbers_found_nowhere():
    answer = ("Wind would supply 51 percent of the 11.5 TW, about 5.965 TW [1]: "
              "\\(0.51 \\times 11.5 = 5.965\\). The plan needs 3.8 million turbines and 1.7 billion rooftop systems in 2030.")
    evidence = PLAN + " in 2030"
    assert stray_numbers(answer, evidence) == ["5.965"]
    # A verified calculation result in the evidence makes the rounded figure acceptable.
    assert stray_numbers("Wind would supply about 5.87 TW [2].", evidence + " Result = 5.865 TW") == []


def test_output_guard_accepts_page_numbers_from_source_metadata():
    from guardrails.output_guard import OutputGuardrail
    guard = OutputGuardrail()
    guard._judge = lambda prompt: {"claims": [{"claim": "The plan is described on page 47", "verdict": "supported"}]}
    sources = [{"n": 1, "kind": "chunk", "page": 47, "title": "The plan", "section": "", "snippet": PLAN, "chunk_id": "c1"}]
    result = guard.verify("Where is the plan?", "The plan is described on page 47 [1].", sources=sources)
    assert result.unsupported_claims == []
    assert result.faithfulness_score == 1.0
