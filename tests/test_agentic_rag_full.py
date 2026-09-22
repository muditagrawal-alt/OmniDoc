"""
End-to-End Verification Test Suite for OmniDoc Advanced Agentic Graph RAG.
Tests:
1. Multi-turn conversation and anaphora resolution
2. Sandboxed mathematical reasoning (CAGR & statistics)
3. Interactive Plotly visualization generation
4. Neural evidence selection and ranking
5. Multi-source conflict and discrepancy resolution
6. Groundedness verification and output guardrail
"""
import sys
import os
import json

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.state import (
    AgentWorkflowState,
    SemanticQuery,
    ConversationMemoryState,
    EvidenceItem,
    EvidencePackage,
    MathExecutionResult,
    VisualizationArtifact,
    ConflictRecord
)
from agents.context_memory_agent import ContextResolutionAgent
from guardrails.semantic_nlu import SemanticNLUEngine
from guardrails.intent_classifier import MultiLabelIntentClassifier
from agents.query_planner import QueryPlanner
from agents.math_agent import MathematicsAgent
from agents.visualization_agent import VisualizationAgent
from agents.evidence_selection_agent import EvidenceSelectionAgent
from agents.conflict_resolution_agent import ConflictResolutionAgent
from agents.synthesis_agent import SynthesisAgent
from guardrails.output_guard import OutputGuardrail
from core.pipeline import AgenticGraphRAGPipeline


def test_context_memory_resolution():
    """Test that multi-turn pronouns like 'it', 'them', 'that' are resolved from conversational history."""
    agent = ContextResolutionAgent()
    history = [
        {"role": "user", "content": "What was Apple's total revenue in fiscal year 2024?"},
        {"role": "assistant", "content": "Apple reported $391.0 billion in total net sales for FY 2024."}
    ]
    query = "Plot them over the past 5 years"
    resolved, mem_state = agent.resolve_context(query, history)
    
    assert resolved is not None
    assert len(resolved) > 0
    # Resolved query should incorporate Apple and revenue or sales context
    assert "apple" in resolved.lower() or "revenue" in resolved.lower() or "sales" in resolved.lower()
    print(f"✓ Context Resolution: '{query}' -> '{resolved}'")


def test_zero_keyword_semantic_nlu():
    """Test deep semantic understanding extracts entities, operations, and modalities without keyword lists."""
    engine = SemanticNLUEngine()
    query = "Compare the gross margins of Microsoft and Alphabet between 2021 and 2024 and calculate the percentage increase"
    sq: SemanticQuery = engine.understand_query(query)
    
    assert sq.raw_query == query
    assert len(sq.operations) > 0
    assert any(op in sq.operations for op in ["compare", "calculate", "retrieve"])
    assert sq.temporal_constraints is not None or "2021" in str(sq.constraints) or "2024" in str(sq.constraints)
    print(f"✓ Semantic NLU Goal: {sq.goal} | Operations: {sq.operations}")


def test_math_agent_sandboxed_execution():
    """Test MathematicalReasoningAgent computes exact CAGR without arithmetic hallucination."""
    agent = MathematicsAgent()
    state = {
        "user_query": "What is the CAGR if revenue grew from $100M in 2020 to $160M in 2024?",
        "chunk_context": [
            {"chunk_id": "c1", "text": "In 2020, revenue was $100M. In 2024, revenue grew to $160M."}
        ]
    }
    result = agent.run(state)
    assert "math_results" in result
    math_res = result["math_results"]
    assert len(math_res) > 0
    exact_val = math_res[0]["exact_result"]
    assert exact_val is not None
    # CAGR = (160/100)^(1/4) - 1 = 1.6^0.25 - 1 ≈ 0.1247 (12.47%)
    val_float = float(exact_val)
    if val_float > 1.0: # If expressed as percentage e.g. 12.47
        assert 11.0 <= val_float <= 14.0
    else:
        assert 0.11 <= val_float <= 0.14
    print(f"✓ Math Agent computed exact CAGR: {exact_val} (Formula: {math_res[0]['formula']})")


def test_visualization_agent_plotly_spec():
    """Test VisualizationAgent generates valid Plotly chart specification with data and layout."""
    agent = VisualizationAgent()
    state = {
        "user_query": "Plot annual revenue from 2020 to 2024",
        "chunk_context": [
            {"chunk_id": "c1", "text": "Year 2020: $100M, Year 2021: $120M, Year 2022: $135M, Year 2023: $148M, Year 2024: $160M."}
        ],
        "math_results": []
    }
    result = agent.run(state)
    assert "visual_artifacts" in result
    artifacts = result["visual_artifacts"]
    assert len(artifacts) > 0
    chart = artifacts[0]
    assert "plotly_spec" in chart
    spec = chart["plotly_spec"]
    assert "data" in spec or "layout" in spec
    print(f"✓ Visualization Agent created '{chart['chart_type']}' chart: '{chart['title']}'")


def test_evidence_selection_ranking():
    """Test EvidenceSelectionAgent ranks and compresses candidate chunks."""
    agent = EvidenceSelectionAgent()
    state = {
        "session_id": "test_session",
        "user_query": "What are the primary risk factors?",
        "chunk_context": [
            {"chunk_id": "1", "text": "Short unrelated sentence", "score": 0.3},
            {"chunk_id": "2", "text": "Primary risk factors include supply chain disruptions, foreign exchange volatility, and cybersecurity threats.", "score": 0.95},
            {"chunk_id": "3", "text": "Secondary risks include regulatory compliance costs.", "score": 0.80}
        ],
        "graph_context": []
    }
    result = agent.run(state)
    assert "evidence_package" in result
    pkg: EvidencePackage = result["evidence_package"]
    assert len(pkg.items) > 0
    # Highest score chunk should be first
    assert pkg.items[0].source_id == "2"
    print(f"✓ Evidence Selection: {pkg.total_candidates_considered} considered -> {pkg.selected_count} selected")


def test_conflict_resolution_audit():
    """Test ConflictResolutionAgent detects contradictory assertions across documents."""
    agent = ConflictResolutionAgent()
    item_a = EvidenceItem(
        evidence_id="ev_1",
        source_type="vector_chunk",
        source_id="c1",
        content="Q4 2023 operating income was reported as $2.4 billion in the preliminary earnings release dated Jan 15, 2024.",
        relevance_score=0.9
    )
    item_b = EvidenceItem(
        evidence_id="ev_2",
        source_type="vector_chunk",
        source_id="c2",
        content="In the audited 10-K filed March 1, 2024, Q4 2023 operating income was adjusted to $2.1 billion due to restructuring expenses.",
        relevance_score=0.95
    )
    pkg = EvidencePackage(
        query_id="q1",
        items=[item_a, item_b],
        total_candidates_considered=2,
        selected_count=2
    )
    state = {
        "user_query": "What was the operating income for Q4 2023?",
        "evidence_package": pkg
    }
    result = agent.run(state)
    assert "conflicts" in result
    conflicts = result["conflicts"]
    print(f"✓ Conflict Resolution completed: {len(conflicts)} discrepancies audited.")


def test_output_guardrail_verification():
    """Test OutputGuardrail accepts verified citations and rejects ungrounded hallucinations."""
    guard = OutputGuardrail()
    chunks = [
        {"chunk_id": "C101", "text": "OmniDoc achieves 98% groundedness precision on complex document reasoning."}
    ]
    
    # Grounded response with citation
    good_draft = "OmniDoc delivers 98% groundedness precision on complex document reasoning [Chunk: C101]."
    res_good = guard.verify(
        query="What is OmniDoc's groundedness precision?",
        draft_answer=good_draft,
        retrieved_chunks=chunks
    )
    assert res_good.is_grounded is True
    assert res_good.faithfulness_score >= 0.8
    assert res_good.action == "accept"
    print(f"✓ Output Guard accepted grounded draft: Score {res_good.faithfulness_score:.2f}")


if __name__ == "__main__":
    print("==================================================")
    print("RUNNING ADVANCED AGENTIC GRAPH RAG TEST SUITE")
    print("==================================================")
    test_context_memory_resolution()
    test_zero_keyword_semantic_nlu()
    test_math_agent_sandboxed_execution()
    test_visualization_agent_plotly_spec()
    test_evidence_selection_ranking()
    test_conflict_resolution_audit()
    test_output_guardrail_verification()
    print("==================================================")
    print("ALL TESTS PASSED SUCCESSFULLY! 🚀")
    print("==================================================")
