"""
The conflict audit: two annual reports giving each year's own figures are not a contradiction,
the model is told which document each piece of evidence comes from, and real contradictions
about the same year still come through.
"""
from agents import conflict_resolution_agent as cra
from core.state import EvidenceItem, EvidencePackage


def _item(n, doc_id, text):
    return EvidenceItem(evidence_id=f"ev_{n}", source_type="vector_chunk", source_id=f"c{n}", content=text,
                        provenance={"doc_id": doc_id, "page": 1})


ITEMS = [
    _item(1, "doc_2025", "Subscription revenue grew 20.1 percent to INR 962 crore. Customers who renewed or expanded: 1,840."),
    _item(2, "doc_2024", "Subscription revenue grew 19.9 percent to INR 801 crore. Customers who renewed or expanded: 1,610."),
    _item(3, "doc_press", "In FY2025 subscription revenue grew 18.0 percent, the press release said."),
]
TITLES = {"doc_2025": "Kestrel-Annual-Report-2025.pdf", "doc_2024": "Kestrel-Annual-Report-2024.pdf",
          "doc_press": "Kestrel-Press-Release.pdf"}


def test_different_years_are_not_a_conflict(monkeypatch):
    seen = {}

    def fake_chat_json(model, prompt, **kw):
        seen["prompt"] = prompt
        return {"conflicts": [
            {"conflicting_claim": "Subscription revenue growth", "evidence_a": "E1", "quote_a": "grew 20.1 percent",
             "evidence_b": "E2", "quote_b": "grew 19.9 percent", "resolution_status": "unresolved_uncertainty"},
            {"conflicting_claim": "FY2025 subscription growth", "evidence_a": "E1", "quote_a": "grew 20.1 percent",
             "evidence_b": "E3", "quote_b": "In FY2025 subscription revenue grew 18.0 percent",
             "resolution_status": "resolved", "preferred": "E1", "rationale": "audited report"},
        ]}

    monkeypatch.setattr(cra, "chat_json", fake_chat_json)
    agent = cra.ConflictResolutionAgent(doc_titles=lambda: TITLES)
    pkg = EvidencePackage(query_id="q", items=ITEMS, total_candidates_considered=3, selected_count=3)
    out = agent.run({"user_query": "How did subscription revenue grow?", "evidence_package": pkg})
    claims = [c["conflicting_claim"] for c in out["conflicts"]]
    assert claims == ["FY2025 subscription growth"]  # 2024's report against 2025's is dropped
    assert "Kestrel-Annual-Report-2024.pdf, page 1" in seen["prompt"]


def test_period_check():
    assert cra.different_periods("grew 19.9%", "Report-2024.pdf", "grew 20.1%", "Report-2025.pdf")
    assert not cra.different_periods("FY2025 grew 18%", "Press.pdf", "grew 20.1%", "Report-2025.pdf")
    assert not cra.different_periods("grew 18%", "Press.pdf", "grew 20.1%", "Report-2025.pdf")  # no year on one side
    assert not cra.different_periods("in 2024 and 2025", "a.pdf", "in 2025", "b.pdf")
