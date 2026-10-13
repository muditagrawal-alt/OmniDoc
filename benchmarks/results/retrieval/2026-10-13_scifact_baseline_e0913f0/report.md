# Retrieval run 2026-10-13_scifact_baseline_e0913f0

BEIR scifact: 5,183 documents (5,688 passages), 300 test questions with 339 relevant documents. Commit `e0913f0`.

Embeddings `nomic-embed-text`, reranker `cross-encoder/ms-marco-MiniLM-L-6-v2`. OmniDoc's search takes 12 hybrid candidates per query, reranks up to 30 and hands the top 10 passages to the writer. Exact metrics against the benchmark's judgements; no model grades anything.

| Mode | nDCG@10 | MRR@10 | Recall@10 | Hit@10 | Recall@100 |
|---|---|---|---|---|---|
| bm25 | **0.688** | 0.652 | 0.820 | 0.840 | 0.918 |
| dense | **0.702** | 0.660 | 0.848 | 0.857 | 0.945 |
| hybrid | **0.737** | 0.704 | 0.860 | 0.873 | 0.962 |
| omnidoc | **0.713** | 0.674 | 0.856 | 0.873 | - |
| rerank-100 | **0.678** | 0.644 | 0.806 | 0.820 | - |

- **omnidoc** is what the app's answer writer receives; its documents come from 10 passages, so it can list fewer than 10 documents when an abstract was split in two.
- **rerank-100** puts the 100 best hybrid documents in the cross-encoder's order (by their best passage).
- Hit@10: questions with at least one relevant document in the top 10.

## Cost and speed

- Index: 5,688 passages embedded and stored in 252 s (built at `8a0ccd3`; 0 could not be embedded). Local models only, no API calls.
- OmniDoc's search per question: median 436 ms, 90th percentile 702 ms (embedding the question, hybrid search, reranking).
- Questions that also searched financial names: 17.

## Published results

nDCG@10 on the same questions; setups differ.

- BM25, Elasticsearch [1]: 0.665
- BM25, Pyserini [2]: 0.679
- ColBERT [1]: 0.671
- BM25 top 100 reranked by MiniLM-L6, the cross-encoder OmniDoc uses [1]: 0.688
- BM25 top 100 reranked by monoT5-220M [2]: 0.734
- BM25 top 100 reranked by Cohere Rerank v2 [2]: 0.744
- BM25 top 100 reranked by GPT-4 [2]: 0.750
- BM25 top 100 reranked by monoT5-3B [2]: 0.766

[1] Thakur et al. 2021, BEIR, table 2, https://arxiv.org/abs/2104.08663
[2] Sun et al. 2023, Is ChatGPT Good at Search?, table 1, https://arxiv.org/abs/2304.09542

Notes: OmniDoc at revision C; questions searched as written
