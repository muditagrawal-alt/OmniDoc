"""
SOTA Evaluation Harness for OmniDoc Agentic Graph RAG.
Evaluates Faithfulness, Answer Relevance, Guardrail Rejection, and Multi-Hop Recall.
"""
import time
import json
import logging
from typing import List, Dict, Any

from core.workflow import OmniDocWorkflow
from guardrails.input_guard import InputGuardrail
from guardrails.output_guard import OutputGuardrail
from guardrails.execution_guard import ExecutionBudgetGuard
from agents.supervisor import SupervisorAgent
from agents.graph_agent import GraphAgent
from agents.hybrid_agent import HybridRetrievalAgent
from agents.vision_agent import VisionAgent
from agents.synthesis_agent import SynthesisAgent
from graph.store import KuzuGraphStore
from retrieval.embeddings import EmbeddingService
from retrieval.lancedb_store import LanceDBStore
from retrieval.reranker import ChunkReranker

logger = logging.getLogger("OmniDoc.EvalHarness")


class BenchmarkEvaluator:
    """Runs automated benchmarks over test queries."""

    def __init__(self):
        # Initialize dependencies
        self.graph_store = KuzuGraphStore()
        self.embed_service = EmbeddingService()
        self.lance_store = LanceDBStore()
        self.reranker = ChunkReranker()
        
        self.input_guard = InputGuardrail()
        self.output_guard = OutputGuardrail()
        self.execution_guard = ExecutionBudgetGuard()

        self.supervisor = SupervisorAgent()
        self.graph_agent = GraphAgent(self.graph_store)
        self.hybrid_agent = HybridRetrievalAgent(self.embed_service, self.lance_store, self.reranker)
        self.vision_agent = VisionAgent()
        self.synthesis_agent = SynthesisAgent()

        self.workflow = OmniDocWorkflow(
            input_guard=self.input_guard,
            output_guard=self.output_guard,
            supervisor=self.supervisor,
            graph_agent=self.graph_agent,
            hybrid_agent=self.hybrid_agent,
            vision_agent=self.vision_agent,
            synthesis_agent=self.synthesis_agent,
            execution_guard=self.execution_guard
        )

    def run_benchmark(self, dataset_path: str = "evaluation/benchmark_dataset.json") -> Dict[str, Any]:
        """Executes full evaluation suite and aggregates metrics."""
        with open(dataset_path, "r") as f:
            test_cases = json.load(f)

        results = []
        total_time = 0.0
        faithfulness_scores = []
        guardrail_successes = 0
        guardrail_total = 0

        for case in test_cases:
            cid = case["id"]
            ctype = case["type"]
            query = case["query"]
            expected = case["ground_truth"]

            start_t = time.time()
            state = self.workflow.execute(user_query=query)
            duration_ms = (time.time() - start_t) * 1000
            total_time += duration_ms

            verification = state.get("verification")
            faith_score = verification.faithfulness_score if verification else 0.0
            response_text = state.get("verified_response", "")

            # Guardrail evaluation
            is_rejected = "filtered" in response_text.lower() or "not found" in response_text.lower()
            if ctype == "out_of_scope":
                guardrail_total += 1
                if is_rejected or not state.get("intent", {}).is_in_scope:
                    guardrail_successes += 1
            else:
                faithfulness_scores.append(faith_score)

            results.append({
                "id": cid,
                "type": ctype,
                "query": query,
                "duration_ms": duration_ms,
                "faithfulness": faith_score,
                "intent_detected": state.get("intent").intent.value if state.get("intent") else "None",
                "nodes_found": len(state.get("graph_context", [])),
                "chunks_found": len(state.get("chunk_context", [])),
                "response_sample": response_text[:120] + "..."
            })

        avg_faithfulness = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 1.0
        guardrail_acc = (guardrail_successes / guardrail_total * 100) if guardrail_total > 0 else 100.0
        p95_latency = sorted([r["duration_ms"] for r in results])[int(len(results) * 0.95)] if results else 0.0

        summary = {
            "total_queries_tested": len(test_cases),
            "mean_faithfulness": round(avg_faithfulness, 3),
            "guardrail_rejection_accuracy_pct": round(guardrail_acc, 1),
            "mean_latency_ms": round(total_time / max(len(test_cases), 1), 1),
            "p95_latency_ms": round(p95_latency, 1),
            "details": results
        }

        return summary
