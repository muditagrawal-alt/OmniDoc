# Benchmark history

Every run of `benchmarks/bench.py` on the same fixed question sets (see `benchmarks/README.md`).
Accuracy is graded by the judge model against the benchmark's reference answers.

| Run | Commit | Answer model | FinanceBench | MMLongBench-Doc | MMLB F1 | Unanswerable declined | Gold page cited | First word (median) | Full answer (median) | Model calls / question |
|---|---|---|---|---|---|---|---|---|---|---|
| [2026-10-09_baseline_08db0eb](2026-10-09_baseline_08db0eb/report.md) | `08db0eb` | nvidia/nemotron-3-super-120b-a12b | 30.6% | 35.8% | 29.0% | 90.0% | 37.9% | 5.0s | 7.5s | 2.5 |
| [2026-10-10_revision-a_8805552](2026-10-10_revision-a_8805552/report.md) | `8805552` | nvidia/nemotron-3-super-120b-a12b | 50.0% | 47.2% | 44.4% | 70.0% | 49.8% | 10.3s | 22.6s | 3.0 |
| [2026-10-10_revision-b_c289454](2026-10-10_revision-b_c289454/report.md) | `c289454` | nvidia/nemotron-3-super-120b-a12b | 38.9% | 49.1% | 50.6% | 60.0% | 47.6% | 7.0s | 9.2s | 3.0 |
| [2026-10-13_revision-c_991bbaa](2026-10-13_revision-c_991bbaa/report.md) | `991bbaa` | nvidia/nemotron-3-super-120b-a12b | 69.4% | 64.2% | 62.8% | 70.0% | 78.6% | 10.1s | 13.3s | 4.0 |

Caveats:

- **2026-10-10_revision-b_c289454**: Revision B as committed dropped the text of every document it added picture descriptions to (fixed in a3ea0bb and 112af5d): 7 of the 24 FinanceBench filings and all 7 MMLongBench-Doc documents were answered from their picture descriptions alone, so this run measures that bug, not the intended revision.
