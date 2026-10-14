# Benchmarks

OmniDoc's answers are measured on two public document question-answering benchmarks with
reference answers and evidence pages, its search on its own with a retrieval benchmark
([below](#retrieval-benchmark-beir-scifact)), and its answers on that benchmark's library with RAGAS
([below](#answers-on-scifact-with-ragas)). Every run is kept in [`results/`](results/), and
[`results/HISTORY.md`](results/HISTORY.md) compares them, so the effect of each change can be seen.

| Benchmark | What it tests | Sample used |
|---|---|---|
| [FinanceBench](https://github.com/patronus-ai/financebench) (Patronus AI, CC BY-NC 4.0) | Questions on real SEC filings (10-K, 10-Q, 8-K, earnings releases): figures, tables, ratios and financial judgement over documents of 15 to 392 pages | 36 of the 150 open-source questions, 12 of each type (metrics-generated, domain-relevant, novel-generated), over 24 filings |
| [MMLongBench-Doc](https://huggingface.co/datasets/yubo2333/MMLongBench-Doc) (NeurIPS 2024 Datasets & Benchmarks) | Long PDFs of seven kinds with evidence in text, layout, tables, charts and figures; questions across pages; unanswerable questions that test whether the answer is made up | One document of each of the 7 kinds, all of its questions: 53 questions: 10 unanswerable, 23 that need a figure and 5 a chart |

The samples were drawn once with a fixed seed (2026) and are stored in [`manifests/`](manifests/),
so the baseline and every later run answer exactly the same questions.

### Development split

Changes are tried out on a separate development split, so the test questions above only
measure a finished revision and are not tuned against. It uses other documents (none of the
test filings or PDFs), other questions and another seed (2027): 18 FinanceBench questions
(6 per type) over 10 filings, and every question of 4 MMLongBench-Doc documents of 4 randomly
chosen kinds (31 questions). Pass `--split dev` to `fetch`, `index` and `run`; development runs
get their own indexes (`benchmarks/work/<benchmark>-dev`) and are stored under
`results/dev/`, outside the history.

## How a run works

1. A separate OmniDoc server starts on port 8011 with its own data folder (`benchmarks/work/`),
   so your library is never touched.
2. The documents are uploaded through the API, as a user would, and the run waits for the
   background summaries, field extraction and knowledge graph to finish. The index is reused by
   later runs until the parsing or indexing code (or the embedding model) changes.
3. Each question is asked through the streaming chat endpoint, scoped to its own document, with
   web search off (the answers to FinanceBench are on the web).
4. The models are pinned and local fallback is off, so a run never silently switches models:

   | Role | Model |
   |---|---|
   | Answers and internal steps | NVIDIA NIM `nvidia/nemotron-3-super-120b-a12b` |
   | Figures and charts | Gemini `gemini-3.5-flash-lite` (500 free requests/day; 3.5 Flash allows only 20) |
   | Embeddings | `nomic-embed-text` (local Ollama) |
   | Grading | Groq `openai/gpt-oss-120b` (another model family than the answers) |

5. The judge compares every answer with the reference answer and decides whether it is correct
   and whether OmniDoc declined to answer. Figures may differ in rounding or scale
   (1,577 million = $1.577 billion); unanswerable questions count as correct only when declined.

## Metrics

- **Accuracy**: share of questions answered correctly, with a 95% confidence interval (Wilson).
  With 36 and 53 questions, differences of a few points are within noise.
- **Wrong answers** and **declined** answers, reported separately: a wrong answer is worse than
  an honest "the document does not say".
- **Unanswerable questions correctly declined** and **F1** as defined by MMLongBench-Doc
  (precision over the questions OmniDoc answered, recall over the answerable ones).
- **Gold page among the sources / cited sources**: whether the page holding the evidence was
  retrieved, and whether the answer cites it.
- **Speed**: time to the first word and to the full answer (median and 90th percentile).
- **Cost**: model calls and tokens per question.

## Running it

```bash
.venv/bin/python -I benchmarks/bench.py fetch                       # questions and documents (about 90 MB)
.venv/bin/python -I benchmarks/bench.py run --label baseline        # both benchmarks
.venv/bin/python -I benchmarks/bench.py run --label smoke --limit 3 # quick check, kept out of the history
.venv/bin/python -I benchmarks/bench.py run --label try-x --split dev   # try a change on the development split
.venv/bin/python -I benchmarks/bench.py run --label x --resume benchmarks/results/<run>   # continue a run
.venv/bin/python -I benchmarks/bench.py judge benchmarks/results/<run> --regrade
.venv/bin/python -I benchmarks/bench.py report                      # rebuild every report and HISTORY.md
```

The NVIDIA, Gemini and Groq keys come from `.env`. Other models can be pinned with
`--provider`, `--model`, `--vision`, `--embed` and `--judge`. A first run of both benchmarks
ingests about 4,000 pages (roughly 700 model calls in the background) and asks 89 questions.

Each run folder holds `config.json` (commit, models, settings), `results.jsonl` (every answer
with its sources, citations, timings and model usage), `judgments.jsonl`, `summary.json` and
`report.md` (metrics, breakdowns and the questions it missed).

## Retrieval benchmark: BEIR SciFact

[`beir.py`](beir.py) measures the search alone, the way retrieval systems are compared in
research. [BEIR](https://github.com/beir-cellar/beir) SciFact (Thakur et al., NeurIPS 2021
Datasets & Benchmarks) has 5,183 scientific abstracts and 300 test claims, each with the abstracts
judged to support or refute it. The abstracts are indexed with OmniDoc's own chunker, embeddings
and LanceDB store (about 6 minutes, local models, no API calls), every claim is searched, and
nDCG@10, MRR@10 and Recall@k are computed against the judgements. No model grades anything, so
the numbers compare directly with published retrievers.

Each run scores five ways of searching the same index: BM25 alone, embeddings alone, both fused
(hybrid), **OmniDoc's search** (the 10 passages the answer writer receives: hybrid candidates
reranked by the cross-encoder, fused with the hybrid order) and the cross-encoder alone over the
100 best hybrid documents. OmniDoc's search scores nDCG@10 0.732, above published BM25 (0.665 to
0.679) and BM25 reranked by the same MiniLM cross-encoder (0.688), below large rerankers such as
monoT5-3B (0.766); see [`results/retrieval/HISTORY.md`](results/retrieval/HISTORY.md). Changes
are tried on SciFact's 809 train claims first (`--split train`, stored under
`results/retrieval/dev/`).

```bash
.venv/bin/python -I benchmarks/beir.py fetch                    # 2.8 MB
.venv/bin/python -I benchmarks/beir.py run --label baseline     # index once, then about 15 minutes
.venv/bin/python -I benchmarks/beir.py run --label try-x --split train --modes bm25,dense,hybrid,omnidoc
.venv/bin/python -I benchmarks/beir.py report                   # rebuild every report and HISTORY.md
```

Each run folder holds `config.json`, `metrics.json`, `rankings.jsonl` (the relevant and the top
10 documents of every claim in every mode) and `report.md`.

## Answers on SciFact with RAGAS

[`ragas_eval.py`](ragas_eval.py) measures whole answers on the same library: OmniDoc answers each
of the 300 BEIR SciFact test claims as a user would ask it ("Is it true that ...?"), searching all
5,183 abstracts, with the QA benchmarks' models pinned and web search off. The 300 claims are
SciFact's labelled dev set (Wadden et al., EMNLP 2020): 124 supported, 64 refuted and 112 for which
the cited abstract holds no evidence. Each answer is scored against the gold label and evidence, and
with [RAGAS](https://github.com/explodinggradients/ragas) (Es et al., EACL 2024):

| Measure | How |
|---|---|
| Verdict accuracy (supported / refuted / not enough evidence) | the judge reads the answer's verdict; compared with the gold label. Also on the 188 claims with gold evidence alone, since an open library may hold evidence for the others |
| Gold evidence among the passages the answer was written from, and cited | exact |
| Faithfulness: are the answer's statements backed by the passages it was given? | RAGAS, judge |
| Answer relevancy | RAGAS, judge and embeddings |
| Factual correctness (recall of the gold rationale) | RAGAS, judge; recall because the rationale is a few sentences and a good answer says more |

The judge is `openai/gpt-oss-20b` on NVIDIA's free API (another family than the Nemotron answer
model; low reasoning effort, which gave the same verdicts in half the time). RAGAS runs in its own
environment so its LangChain pins never touch the app's:

```bash
python3.12 -m venv benchmarks/work/ragas-venv
benchmarks/work/ragas-venv/bin/pip install ragas==0.4.3 langchain-community==0.3.31 "langchain<1" "langchain-core<1" "langchain-openai<1"
.venv/bin/python -I benchmarks/ragas_eval.py fetch                          # gold labels and rationales
.venv/bin/python -I benchmarks/ragas_eval.py answer --label baseline         # about 2 hours (free-tier pacing)
benchmarks/work/ragas-venv/bin/python -I benchmarks/ragas_eval.py score benchmarks/results/ragas/<run>   # 2 to 4 hours
.venv/bin/python -I benchmarks/ragas_eval.py report                         # rebuild reports and HISTORY.md
```

`answer --code <folder>` answers with another copy of the app (a revision being tried), `--split
train --sample N` uses other claims for development, and `score --metrics verdict` grades verdicts
only. Runs are kept in [`results/ragas/`](results/ragas/) and compared in `results/ragas/HISTORY.md`.
