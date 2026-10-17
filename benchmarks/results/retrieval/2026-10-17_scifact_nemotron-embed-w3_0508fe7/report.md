# Retrieval run 2026-10-17_scifact_nemotron-embed-w3_0508fe7

BEIR scifact: 5,183 documents (5,688 passages), 300 test questions with 339 relevant documents. Commit `0508fe7`.

Embeddings `nvidia:nvidia/nemotron-3-embed-1b`, reranker `cross-encoder/ms-marco-MiniLM-L-6-v2`, vector ranking weighted 3x against keywords. OmniDoc's search takes 12 hybrid candidates per query, reranks up to 30 and hands the top 10 passages to the writer. Exact metrics against the benchmark's judgements; no model grades anything.

| Mode | nDCG@10 | MRR@10 | Recall@10 | Hit@10 | Recall@100 |
|---|---|---|---|---|---|
| bm25 | **0.688** | 0.652 | 0.820 | 0.840 | 0.918 |
| dense | **0.754** | 0.727 | 0.866 | 0.877 | 0.960 |
| hybrid | **0.753** | 0.722 | 0.875 | 0.887 | 0.977 |
| omnidoc | **0.742** | 0.709 | 0.865 | 0.877 | - |
| rerank-100 | **0.680** | 0.647 | 0.809 | 0.823 | - |

- **omnidoc** is what the app's answer writer receives; its documents come from 10 passages, so it can list fewer than 10 documents when an abstract was split in two.
- **rerank-100** puts the 100 best hybrid documents in the cross-encoder's order (by their best passage).
- Hit@10: questions with at least one relevant document in the top 10.

## Cost and speed

- Index: 5,688 passages embedded and stored in 2 s (built at `9363f8a`; 0 could not be embedded). Local models only, no API calls.
- OmniDoc's search per question: median 321 ms, 90th percentile 464 ms (embedding the question, hybrid search, reranking).
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

Notes: NVIDIA nemotron-3-embed-1b (hosted, free) with the vector ranking weighted 3x against keywords (OMNIDOC_DENSE_WEIGHT=3), the setting chosen on the train questions
