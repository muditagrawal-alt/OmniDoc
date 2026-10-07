# OmniDoc

OmniDoc is a local-first document intelligence workspace. Add PDFs, Word files, text or Markdown, then ask questions in plain language. A team of agents searches the documents, walks a knowledge graph built from them, reads their figures, runs exact calculations and writes an answer in which every claim cites the passage it came from. A verifier then checks the answer against those sources and says how well it is supported.

Everything runs on your machine through [Ollama](https://ollama.com). Documents, vectors, the graph and conversations stay in a local data folder.

## What you can do

- **Ask with citations.** Answers cite numbered sources (`[1]`, `[2]`) that open the exact passage, page and section. Each answer shows a verification badge: supported, partly supported, or not verified.
- **Watch the agents work.** Every step (understanding the question, planning, searching, reading figures, computing, writing, verifying) streams to the UI as it runs.
- **Explore the knowledge globe.** Entities and relations extracted from your documents are laid out on an interactive 3D globe: communities cluster together, related entities sit near each other, and you can search, filter by document or category, inspect an entity and ask about it.
- **Get charts and calculations from the evidence.** Charts are drawn only from numbers present in the sources, with a table view and CSV/SVG export. Calculations run in a restricted SymPy evaluator and show their formula, inputs and assumptions.
- **Read figures.** Charts, diagrams and scanned images inside PDFs are read by a local vision model.
- **Ask in Indian languages.** Answers can be written in Hindi, Marathi, Tamil, Telugu, Kannada, Assamese, Bengali or Gujarati, with voice input and read-aloud in the browser.
- **Export reports.** Any conversation exports to PDF or Word, with sources, calculations and tables.

## How a question is answered

```text
question
  → input guard           blocks prompt injection and abuse, allows sensitive topics found in your documents
  → context resolution    resolves "it", "that company", ... from the conversation
  → understanding         entities, constraints, intent
  → planner + supervisor  decide which agents the question needs
  → entity resolution, query expansion
  → retrieval             hybrid search (LanceDB vectors + BM25, reciprocal rank fusion, cross-encoder rerank)
                          knowledge-graph neighbourhood (Kùzu)
                          figure reading (local vision model)
  → evidence selection    one numbered evidence list shared by every later step
  → conflict check        flags sources that disagree
  → math, charts          only from numbers in the evidence
  → cited synthesis       answer with [n] citations
  → output guard          claim-by-claim check against the evidence; one rewrite if claims are unsupported
```

Documents are parsed with PyMuPDF (fast mode, used for uploads) or IBM Docling, chunked by section, embedded with `nomic-embed-text` and indexed. Knowledge-graph extraction runs in the background after upload, so documents are searchable immediately and the graph fills in over a few minutes.

## Quick start

**Requirements:** Python 3.9+, Node.js 20+, and Ollama.

```bash
# 1. Models
ollama pull qwen2.5:7b-instruct      # reasoning and writing
ollama pull nomic-embed-text         # embeddings
ollama pull qwen3.5:9b               # optional: reads figures (gemma4:12b also works)

# 2. Backend (http://127.0.0.1:8000)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py

# 3. Frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

PDF export uses WeasyPrint, which needs Pango on macOS: `brew install pango`.

The first run downloads the cross-encoder reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) from Hugging Face; after that OmniDoc works offline.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OMNIDOC_MODEL` | `qwen2.5:7b-instruct` | Ollama model for every reasoning step (also switchable in the app) |
| `OMNIDOC_VISION_MODEL` | first installed of `qwen3.5:9b`, `gemma4:12b`, `qwen2.5vl:7b`, `llama3.2-vision:11b` | Model that reads figures |
| `OMNIDOC_VISION_MAX_FIGURES` | `2` | Figures read per question |
| `OMNIDOC_DATA_DIR` | `./.data` | Database, vectors, graph, uploads and figures |
| `OMNIDOC_GRAPH_CHUNKS` | `40` | Sections per document used for graph extraction |
| `OMNIDOC_NUM_CTX` | `8192` | Context window requested from Ollama |
| `OMNIDOC_LLM_TIMEOUT` / `OMNIDOC_EMBED_TIMEOUT` | `300` / `120` | Request timeouts in seconds |
| `OMNIDOC_RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranker |
| `OMNIDOC_MAX_UPLOAD_MB` | `100` | Upload size limit |
| `OMNIDOC_CORS_ORIGINS` | local Vite dev and preview origins | Browser origins allowed to call the API |
| `OMNIDOC_HOST` / `OMNIDOC_PORT` | `127.0.0.1` / `8000` | API address |
| `OMNIDOC_WARMUP` | `1` | Load models in the background when the server starts |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama address |
| `VITE_API_BASE` | same origin (Vite proxies `/api`) | API base URL for the frontend build |

## Project layout

```text
server.py              FastAPI API: profiles and sessions, conversations, streaming queries, documents, graph, export
db_store.py            SQLite persistence
core/                  LangGraph workflow, shared state, pipeline (ingestion + querying)
agents/                planner, supervisor, retrieval, graph, vision, evidence, conflict, math, charts, synthesis, citations
guardrails/            input guard, intent, semantic NLU, execution budget, output verification
retrieval/             LanceDB store, embeddings, reranker
graph/                 Kùzu store, schema, triple extraction
parsing/               Docling and PyMuPDF parsing, chunking, figure extraction
export/                PDF (WeasyPrint) and Word (python-docx) reports
frontend/              React 19 + TypeScript app: chat, library, knowledge globe (three.js), charts
tests/                 API, export and agent tests
evaluation/            small hand-written example harness
```

`app.py` is the earlier Streamlit prototype; the React app is the maintained interface.

## Tests

```bash
pytest tests/test_grounding.py tests/test_server_endpoints.py tests/test_report_compiler.py   # fast, no model calls
pytest tests/test_agentic_rag_full.py                                                     # calls the local model
cd frontend && npx tsc -p tsconfig.app.json --noEmit && npx oxlint src && npm run build
```

The API tests run against a temporary data folder and never touch `.data/`.

## Evaluation

`evaluation/` runs a few hand-written questions as a smoke test; its numbers are not benchmark results. Public benchmarks that fit OmniDoc include OmniDocBench and olmOCR-Bench (parsing), MultiHop-RAG and FinanceBench (cited QA), GraphRAG-Bench (graph retrieval), MMLongBench-Doc and UniDoc-Bench (long multimodal documents), ViDoRe v3 (visual retrieval) and RAGTruth (hallucination detection).

## Privacy

Inference, embeddings, figure reading, storage and export all run locally. The API accepts browser requests only from the local frontend origins, sessions use opaque tokens, and conversations are private to the profile that created them. Fonts and libraries are bundled with the frontend, so the app makes no third-party requests.

## License

MIT
