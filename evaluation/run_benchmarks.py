"""
CLI runner for OmniDoc SOTA Evaluation Benchmarks.
Usage: python evaluation/run_benchmarks.py
"""
import json
import sys
from evaluation.eval_harness import BenchmarkEvaluator


def main():
    print("=========================================================")
    print("🚀 Running OmniDoc SOTA Agentic Graph RAG Benchmark Suite")
    print("=========================================================")
    evaluator = BenchmarkEvaluator()
    summary = evaluator.run_benchmark()

    print("\n--- BENCHMARK RESULTS SUMMARY ---")
    print(f"Total Queries Evaluated:          {summary['total_queries_tested']}")
    print(f"Mean Faithfulness Score:          {summary['mean_faithfulness']} / 1.00")
    print(f"Guardrail Rejection Accuracy:     {summary['guardrail_rejection_accuracy_pct']}%")
    print(f"Mean Latency:                     {summary['mean_latency_ms']} ms")
    print(f"P95 Latency:                      {summary['p95_latency_ms']} ms")
    print("---------------------------------------------------------")
    
    print("\nPer-Query Details:")
    for d in summary["details"]:
        print(f"[{d['id']}] Type: {d['type']:<22} | Intent: {d['intent_detected']:<20} | Faith: {d['faithfulness']} | {d['duration_ms']:.0f}ms")
        print(f"  Q: {d['query']}")
        print(f"  A: {d['response_sample']}\n")

    # Save to disk
    with open("evaluation/benchmark_report.json", "w") as f:
        json.dump(summary, f, indent=2)
    print("Full report written to evaluation/benchmark_report.json")


if __name__ == "__main__":
    main()
