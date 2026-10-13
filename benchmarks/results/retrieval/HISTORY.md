# Retrieval history

Every run of `benchmarks/beir.py`: nDCG@10 per search mode on the BEIR test questions (exact metrics, no judge). OmniDoc's search is the column that matters: it is what the answer writer receives.

| Run | Dataset | Commit | BM25 | Dense | Hybrid | OmniDoc search | Hit@10 | Rerank 100 | Recall@100 (hybrid) |
|---|---|---|---|---|---|---|---|---|---|
| [2026-10-13_scifact_baseline_e0913f0](2026-10-13_scifact_baseline_e0913f0/report.md) | scifact | `e0913f0` | 0.688 | 0.702 | 0.737 | **0.713** | 0.873 | 0.678 | 0.962 |
| [2026-10-14_scifact_prefixes-fusion_4515e3e](2026-10-14_scifact_prefixes-fusion_4515e3e/report.md) | scifact | `4515e3e` | 0.688 | 0.705 | 0.732 | **0.732** | 0.863 | 0.678 | 0.958 |
