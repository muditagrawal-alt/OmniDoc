"""
End-to-End Workflow Execution Test for OmniDoc Agentic Graph RAG.
Tests full pipeline query with mock document chunks and execution plan.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pipeline import AgenticGraphRAGPipeline

def test_full_pipeline_query():
    print("\n--- Initializing AgenticGraphRAGPipeline ---")
    pipeline = AgenticGraphRAGPipeline()
    
    # 1. Ingest test mock knowledge into lance & graph or query with direct questions
    query = "Calculate the revenue growth rate if 2020 revenue was $50M and 2024 revenue was $85M, and plot the progression"
    print(f"\n--- Testing Pipeline Query: '{query}' ---")
    
    result = pipeline.query(
        user_query=query,
        session_id="test_e2e_session",
        conversation_history=[
            {"role": "user", "content": "Tell me about the financial performance."},
            {"role": "assistant", "content": "The company demonstrated strong financial growth from 2020 to 2024."}
        ]
    )
    
    print("\n=== PIPELINE EXECUTION RESULTS ===")
    print(f"Goal / Plan: {result.get('plan')}")
    print(f"Math Results: {len(result.get('math_results', []))} calculation(s)")
    for m in result.get("math_results", []):
        print(f"  - Formula: {m.get('formula')} -> Exact Result: {m.get('exact_result')} {m.get('units', '')}")
    
    print(f"Visual Artifacts: {len(result.get('visual_artifacts', []))} chart(s)")
    for v in result.get("visual_artifacts", []):
        print(f"  - Chart: {v.get('chart_type')} ('{v.get('title')}')")
    
    print(f"Conflicts Audited: {len(result.get('conflicts', []))}")
    print(f"\nVerified Response:\n{result.get('verified_response') or result.get('draft_response')}")
    
    if result.get("verification"):
        v = result["verification"]
        print(f"\nOutput Guard Groundedness Score: {v.faithfulness_score} (Action: {v.action})")

if __name__ == "__main__":
    test_full_pipeline_query()
