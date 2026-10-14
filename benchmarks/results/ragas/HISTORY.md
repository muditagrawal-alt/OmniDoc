# RAGAS history

Every run of `benchmarks/ragas_eval.py` on the BEIR SciFact test claims: verdicts and evidence are scored exactly, the RAGAS metrics by a judge model of another family than the answer model.

| Run | Commit | Answers | Verdict accuracy | On claims with evidence | Macro-F1 | Gold evidence in context | Faithfulness | Faithfulness (verdicts) | Answer relevancy | Factual correctness (recall) | Judge |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [2026-10-14_scifact_baseline_5b02d5c](2026-10-14_scifact_baseline_5b02d5c/report.md) | `5b02d5c` | 300 | **77.0%** | 86.2% | 76.6% | 97.9% | 75.8% | 85.7% | 81.0% | 42.5% | nvidia:openai/gpt-oss-20b |
| [2026-10-14_scifact_revision-d_caae796](2026-10-14_scifact_revision-d_caae796/report.md) | `caae796` | 300 | **78.0%** | 87.2% | 77.5% | 97.9% | 75.7% | 86.0% | 80.1% | 44.5% | nvidia:openai/gpt-oss-20b |
