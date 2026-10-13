# Retrieval run 2026-10-13_scifact-train_baseline_19de8de

BEIR scifact: 5,183 documents (5,688 passages), 809 train questions with 919 relevant documents. Commit `19de8de`.

Embeddings `nomic-embed-text`, reranker `cross-encoder/ms-marco-MiniLM-L-6-v2`. OmniDoc's search takes 12 hybrid candidates per query, reranks up to 30 and hands the top 10 passages to the writer. Exact metrics against the benchmark's judgements; no model grades anything.

| Mode | nDCG@10 | MRR@10 | Recall@10 | Hit@10 | Recall@100 |
|---|---|---|---|---|---|
| bm25 | **0.701** | 0.673 | 0.809 | 0.827 | 0.927 |
| dense | **0.720** | 0.689 | 0.841 | 0.855 | 0.948 |
| hybrid | **0.745** | 0.717 | 0.857 | 0.871 | 0.966 |
| omnidoc | **0.729** | 0.695 | 0.854 | 0.868 | - |

- **omnidoc** is what the app's answer writer receives; its documents come from 10 passages, so it can list fewer than 10 documents when an abstract was split in two.
- Hit@10: questions with at least one relevant document in the top 10.

## Cost and speed

- Index: 5,688 passages embedded and stored in 252 s (built at `8a0ccd3`; 0 could not be embedded). Local models only, no API calls.
- OmniDoc's search per question: median 359 ms, 90th percentile 800 ms (embedding the question, hybrid search, reranking).
- Questions that also searched financial names: 61.

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

Notes: revision C, before retrieval changes
