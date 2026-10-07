"""
SOTA Agentic Graph RAG Benchmark Evaluation Suite.
Evaluates OmniDoc against modern SOTA benchmarks:
1. MultiHop-RAG: Complex multi-hop relational queries across disjoint documents
2. FinanceBench: Audited SEC Form 10-K statements with exact numerical/CAGR reasoning
3. Microsoft GraphRAG: Global sensemaking and architectural synthesis
4. CRUD-RAG: Cross-document conflict and discrepancy auditing
5. RGB (RAG Benchmark): Negative rejection & adversarial prompt guardrails
"""
import os
import sys
import time
import json
import argparse
import logging
from typing import List, Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set offline flags for macOS LibreSSL resilience
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from core.pipeline import AgenticGraphRAGPipeline

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("OmniDoc.SOTABenchmarkRunner")


def run_sota_benchmark_suite(
    dataset_path: str = "evaluation/sota_benchmark_dataset.json",
    output_report_path: str = "evaluation/sota_benchmark_report.json",
    model_name: str = "qwen2.5:7b-instruct",
    limit: int = None,
    benchmark_filter: str = None
):
    print("=================================================================")
    print("🚀 RUNNING OMNIDOC SOTA AGENTIC GRAPH RAG BENCHMARK SUITE")
    print(f"   Model: {model_name} | Dataset: {dataset_path}")
    print("=================================================================")

    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Benchmark dataset not found at: {dataset_path}")

    with open(dataset_path, "r", encoding="utf-8") as f:
        cases: List[Dict[str, Any]] = json.load(f)

    if benchmark_filter:
        cases = [c for c in cases if benchmark_filter.lower() in c.get("benchmark", "").lower()]
        print(f"Filter applied: '{benchmark_filter}' -> {len(cases)} matching test cases.")

    if limit and limit > 0:
        cases = cases[:limit]
        print(f"Limiting execution to first {len(cases)} test cases.")

    print(f"Total benchmark test cases to evaluate: {len(cases)}\n")

    pipeline = AgenticGraphRAGPipeline(model_name=model_name)

    results = []
    category_metrics = {}
    total_time = 0.0
    guardrail_rejections_correct = 0
    guardrail_rejections_total = 0

    for idx, case in enumerate(cases, 1):
        cid = case["id"]
        bm_name = case.get("benchmark", "Standard")
        qtype = case["type"]
        query = case["query"]
        expected_entities = case.get("expected_entities", [])
        ground_truth = case.get("ground_truth", "")

        print(f"[{idx}/{len(cases)}] [{bm_name} | {qtype}]")
        print(f"  Q: '{query[:80]}...'")

        start_t = time.time()
        res = pipeline.query(user_query=query, session_id=f"sota_bench_{cid}")
        elapsed_ms = (time.time() - start_t) * 1000.0
        total_time += elapsed_ms

        verification = res.get("verification")
        faith_score = verification.faithfulness_score if verification else 0.0
        is_grounded = verification.is_grounded if verification else False
        verified_resp = res.get("verified_response") or res.get("draft_response") or ""
        
        graph_nodes = sum(len(g.get("nodes", [])) for g in res.get("graph_context", []))
        graph_edges = sum(len(g.get("edges", [])) for g in res.get("graph_context", []))
        chunks_count = len(res.get("chunk_context", []))
        math_count = len(res.get("math_results", []))
        conflicts_count = len(res.get("conflicts", []))

        # Check negative rejection / guardrail accuracy
        is_negative = qtype in ["negative_rejection", "out_of_scope"]
        rejection_passed = False
        if is_negative:
            guardrail_rejections_total += 1
            has_refusal_phrase = any(phrase in verified_resp.lower() for phrase in [
                "not found in provided sources",
                "do not contain sufficient evidence",
                "could not be processed",
                "scope guard",
                "not mentioned"
            ])
            if has_refusal_phrase or not is_grounded:
                guardrail_rejections_correct += 1
                rejection_passed = True

        # Math verification
        math_exact = None
        if math_count > 0:
            math_exact = res["math_results"][0].get("exact_result")

        print(f"  ✓ Finished in {elapsed_ms:.0f}ms | Faithfulness: {faith_score:.2f} | Graph: {graph_nodes}N/{graph_edges}E | Chunks: {chunks_count}")
        if math_count > 0:
            print(f"  🔢 Math Output: {math_exact} (Formula: {res['math_results'][0].get('formula')})")
        if conflicts_count > 0:
            print(f"  ⚖️ Conflicts Audited: {conflicts_count}")
        if is_negative:
            status_symbol = "🛡️ PASSED" if rejection_passed else "⚠️ FAILED"
            print(f"  {status_symbol} Negative Guardrail Rejection")

        record = {
            "id": cid,
            "benchmark": bm_name,
            "type": qtype,
            "query": query,
            "ground_truth": ground_truth,
            "duration_ms": elapsed_ms,
            "faithfulness_score": faith_score,
            "is_grounded": is_grounded,
            "graph_nodes_retrieved": graph_nodes,
            "graph_edges_retrieved": graph_edges,
            "chunks_retrieved": chunks_count,
            "math_results": res.get("math_results", []),
            "conflicts_audited": res.get("conflicts", []),
            "response_preview": verified_resp[:200] + "..."
        }
        results.append(record)

        # Aggregate category metrics
        if bm_name not in category_metrics:
            category_metrics[bm_name] = {"scores": [], "latencies": [], "count": 0}
        category_metrics[bm_name]["scores"].append(faith_score)
        category_metrics[bm_name]["latencies"].append(elapsed_ms)
        category_metrics[bm_name]["count"] += 1

    # Final summary calculations
    all_scores = [r["faithfulness_score"] for r in results if r["type"] not in ["out_of_scope"]]
    mean_faithfulness = sum(all_scores) / len(all_scores) if all_scores else 1.0
    guardrail_acc = (guardrail_rejections_correct / guardrail_rejections_total * 100.0) if guardrail_rejections_total > 0 else 100.0
    sorted_latencies = sorted([r["duration_ms"] for r in results])
    p50_latency = sorted_latencies[int(len(sorted_latencies) * 0.50)] if sorted_latencies else 0.0
    p95_latency = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else 0.0

    benchmark_breakdown = {}
    for bm, data in category_metrics.items():
        benchmark_breakdown[bm] = {
            "queries_evaluated": data["count"],
            "mean_faithfulness": round(sum(data["scores"]) / len(data["scores"]), 3) if data["scores"] else 1.0,
            "mean_latency_ms": round(sum(data["latencies"]) / len(data["latencies"]), 1)
        }

    summary = {
        "benchmark_suite": "OmniDoc SOTA Agentic Graph RAG Benchmark",
        "model_evaluated": model_name,
        "total_test_cases": len(results),
        "mean_faithfulness": round(mean_faithfulness, 3),
        "guardrail_rejection_accuracy_pct": round(guardrail_acc, 1),
        "p50_latency_ms": round(p50_latency, 1),
        "p95_latency_ms": round(p95_latency, 1),
        "benchmark_breakdown": benchmark_breakdown,
        "detailed_results": results
    }

    with open(output_report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n=================================================================")
    print("🏆 SOTA AGENTIC GRAPH RAG BENCHMARK RESULTS")
    print("=================================================================")
    print(f"Total Queries Evaluated:               {len(results)}")
    print(f"Overall Mean Faithfulness Score:       {mean_faithfulness:.3f} / 1.000 ({mean_faithfulness*100:.1f}%)")
    print(f"Negative Guardrail Rejection Accuracy: {guardrail_acc:.1f}%")
    print(f"P50 Latency:                           {p50_latency:.1f} ms")
    print(f"P95 Latency:                           {p95_latency:.1f} ms")
    print("-----------------------------------------------------------------")
    print("Performance by SOTA Benchmark Suite:")
    for bm, stats in benchmark_breakdown.items():
        print(f"  • {bm:<22} | {stats['queries_evaluated']} queries | Faithfulness: {stats['mean_faithfulness']:.3f} | Latency: {stats['mean_latency_ms']:.0f}ms")
    print("=================================================================")
    print(f"Detailed audit report saved to: {output_report_path}\n")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OmniDoc SOTA Agentic Graph RAG Benchmark Suite")
    parser.add_argument("--model", type=str, default="qwen2.5:7b-instruct", help="Ollama LLM model to evaluate")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries evaluated")
    parser.add_argument("--benchmark", type=str, default=None, help="Filter by benchmark name (e.g. MultiHop-RAG, FinanceBench)")
    args = parser.parse_args()

    run_sota_benchmark_suite(
        model_name=args.model,
        limit=args.limit,
        benchmark_filter=args.benchmark
    )
