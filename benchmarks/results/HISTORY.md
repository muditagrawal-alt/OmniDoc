# Benchmark history

Every run of `benchmarks/bench.py` on the same fixed question sets (see `benchmarks/README.md`).
Accuracy is graded by the judge model against the benchmark's reference answers.

| Run | Commit | Answer model | FinanceBench | MMLongBench-Doc | MMLB F1 | Unanswerable declined | Gold page cited | First word (median) | Full answer (median) | Model calls / question |
|---|---|---|---|---|---|---|---|---|---|---|
| [2026-10-09_baseline_08db0eb](2026-10-09_baseline_08db0eb/report.md) | `08db0eb` | nvidia/nemotron-3-super-120b-a12b | 30.6% | 35.8% | 29.0% | 90.0% | 37.9% | 5.0s | 7.5s | 2.5 |
| [2026-10-10_revision-a_8805552](2026-10-10_revision-a_8805552/report.md) | `8805552` | nvidia/nemotron-3-super-120b-a12b | 50.0% | 47.2% | 44.4% | 70.0% | 49.8% | 10.3s | 22.6s | 3.0 |
