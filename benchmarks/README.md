# Benchmarks

OmniDoc is measured on two public document question-answering benchmarks with reference
answers and evidence pages. Every run is kept in [`results/`](results/), and
[`results/HISTORY.md`](results/HISTORY.md) compares them, so the effect of each change can be seen.

| Benchmark | What it tests | Sample used |
|---|---|---|
| [FinanceBench](https://github.com/patronus-ai/financebench) (Patronus AI, CC BY-NC 4.0) | Questions on real SEC filings (10-K, 10-Q, 8-K, earnings releases): figures, tables, ratios and financial judgement over documents of 15 to 392 pages | 36 of the 150 open-source questions, 12 of each type (metrics-generated, domain-relevant, novel-generated), over 24 filings |
| [MMLongBench-Doc](https://huggingface.co/datasets/yubo2333/MMLongBench-Doc) (NeurIPS 2024 Datasets & Benchmarks) | Long PDFs of seven kinds with evidence in text, layout, tables, charts and figures; questions across pages; unanswerable questions that test whether the answer is made up | One document of each of the 7 kinds, all of its questions: 53 questions: 10 unanswerable, 23 that need a figure and 5 a chart |

The samples were drawn once with a fixed seed (2026) and are stored in [`manifests/`](manifests/),
so the baseline and every later run answer exactly the same questions.

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
   | Figures and charts | Gemini `gemini-3.5-flash` |
   | Embeddings | `nomic-embed-text` (local Ollama) |
   | Grading | Gemini `gemini-3.5-flash` (another model family than the answers) |

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
.venv/bin/python -I benchmarks/bench.py run --label x --resume benchmarks/results/<run>   # continue a run
.venv/bin/python -I benchmarks/bench.py judge benchmarks/results/<run> --regrade
.venv/bin/python -I benchmarks/bench.py report                      # rebuild every report and HISTORY.md
```

The NVIDIA and Gemini keys come from `.env`. Other models can be pinned with
`--provider`, `--model`, `--vision`, `--embed` and `--judge`. A first run of both benchmarks
ingests about 4,000 pages (roughly 700 model calls in the background) and asks 89 questions.

Each run folder holds `config.json` (commit, models, settings), `results.jsonl` (every answer
with its sources, citations, timings and model usage), `judgments.jsonl`, `summary.json` and
`report.md` (metrics, breakdowns and the questions it missed).
