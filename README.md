# OmniDoc

OmniDoc is a document intelligence workspace for every kind of document: PDFs, scans and photos, Word files, spreadsheets, slide decks, e-mails, e-books, web pages and audio or video recordings. Ask questions in plain language and a team of agents searches the documents (and the web when needed), walks a knowledge graph built from them, queries their tables with SQL, reads their figures, runs exact calculations and writes an answer in which every claim cites its source. A verifier checks the answer sentence by sentence, and clicking any citation opens the document, or the web page, with the supporting sentence highlighted.

It runs on free hosted model APIs (Gemini, Groq, NVIDIA, Mistral, OpenRouter, ...) or entirely on your machine with [Ollama](https://ollama.com). Documents, indexes, the graph and conversations stay in your data folder.

## What you can do

- **Ask with citations you can check.** Answers cite numbered sources (`[1]`, `[2]`) and stream in as they are written. Clicking a citation opens the document beside the answer at the cited page and highlights the sentence that supports the claim; scanned pages are highlighted from their OCR word positions and recordings play from the cited moment.
- **Search the web, with cited pages.** When a question needs current or general information, or the documents do not answer it, the web search agent searches (Tavily, Brave, Serper, SearXNG or DuckDuckGo without a key), reads the best pages and cites them like documents. A web citation opens the page in OmniDoc's reader with the cited passage highlighted. The composer's Web menu chooses *when needed*, *always* or *never*.
- **Sentence-level citation checking.** Every sentence is checked against the passages it cites. Figures must appear in a cited passage, wrong citation numbers are corrected, and unsupported sentences are underlined with the reason.
- **Any document type.** Scans and photos are read with Tesseract OCR (Indian languages included); slides, e-mails (with attachments), EPUB books and saved web pages keep their structure; recordings are transcribed with timestamps (Whisper). Add a web page or online PDF from its link.
- **Document types, fields and checks.** Each upload is classified (invoice, receipt, purchase order, contract, resume, research paper, bank statement, report, ...). Its template's fields are filled in the background, each with a verbatim quote, and checked (subtotal + tax = total, due date after invoice date, opening + credits − debits = closing). The viewer's Details tab shows them; questions like "total due across all my invoices" are answered from these records with SQL.
- **Ask about tables.** Tables in PDFs, Word, slides and spreadsheets are queried with read-only SQL. Question words are matched to the table's own values by meaning ("solar" finds "Photovoltaic plants" and "Rooftop PV").
- **Fill a form from your documents.** The Extract view fills any set of fields from many documents at once, with a citation per value, and exports CSV or JSON.
- **Compare documents.** The Compare view aligns two versions sentence by sentence and shows modified, added and removed text with word-level differences and changed figures, plus an optional summary of what matters.
- **Find and redact sensitive data.** The viewer's Privacy tab finds Aadhaar (checksum-verified), PAN, GSTIN, IFSC, card (Luhn), account, passport and voter-ID numbers, phone numbers, e-mail addresses and dates of birth, shows each on the page, and downloads a truly redacted copy (text and pixels removed, metadata scrubbed).
- **Summaries across documents.** Every document is summarized after upload; questions about whole documents or the library are answered from the summaries.
- **Explore the knowledge globe.** Entities and relations from your documents on an interactive 3D globe.
- **Charts, calculations and figures.** Charts only from numbers in the sources; exact calculations in a restricted SymPy evaluator; figures read by a vision model.
- **Indian languages.** Ask in Hindi, Marathi, Tamil, Telugu, Kannada, Bengali, Gujarati and more; the documents are searched with English queries and the answer is written in your language.
- **Use OmniDoc from other AI tools.** `mcp_server.py` makes the library available to Claude Desktop, Claude Code, Cursor and other MCP clients.

## How a question is answered

```text
question
  → input guard           empty, oversized or prompt-injection input is refused (no model call)
  → understanding         one fast-model call when it helps (follow-up questions, other languages,
                          several parts), rules otherwise: resolved question, English search queries,
                          sub-questions, entities, intent and needs; context memory, language, intent,
                          entity resolution against the graph and query expansion are derived from it
  → plan                  steps chosen from the needs; a per-question budget of model calls and time
  → hybrid search         vectors + BM25 with document context, reranked; a second search for parts
                          of the question the passages do not cover
  → document intelligence follows "Table 3", "Figure 2", "page 12" and adds the rest of cut-off passages
  → knowledge graph, figures, SQL over tables and library records, document summaries, web search
  → temporal reasoning    dates the evidence, applies the question's time range, orders events
  → evidence selection    one numbered evidence list shared by every later step
  → conflict check        model audit only when figures about the same thing differ across documents
  → math, charts          only when asked for, only from numbers in the evidence
  → cited answer          streamed to the interface as it is written
  → sentence check        citations corrected; one rewrite only if the answer is badly supported
```

A typical question costs two or three model calls (understanding when it helps, writing, checking), down from about ten. The trace under each answer shows the steps, the model calls and which models answered.

## Quick start

**Requirements:** Python 3.9+ and Node.js 20+. Either a free API key (recommended: fast, nothing heavy runs on your computer) or Ollama.

```bash
# 1. Models: copy the template and add at least one free key (see "Free model APIs" below)
cp .env.example .env
#    ...or run models locally instead:
#    ollama pull qwen2.5:7b-instruct && ollama pull nomic-embed-text
brew install tesseract tesseract-lang ffmpeg   # optional: scans and images (OCR), recordings

# 2. Backend (http://127.0.0.1:8000)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py

# 3. Frontend (http://localhost:5173)
cd frontend && npm install && npm run dev
```

`npm run build` in `frontend/` makes `server.py` serve the app itself at http://127.0.0.1:8000. PDF reports use WeasyPrint, which needs Pango on macOS (`brew install pango`).

## Free model APIs

Add keys to `.env` (see [`.env.example`](.env.example)). The first configured provider answers; when it is rate-limited, out of daily quota or too small for a request, the next one takes over, then local Ollama if it runs. Each provider has a strong model for writing and checking and a fast one for understanding questions and background work. Settings → *Free model APIs and web search* shows what is configured.

| Provider | Free tier (October 2026) | Notes |
| --- | --- | --- |
| Google Gemini | Gemini 2.5 Flash / Flash-Lite, embeddings, images; limits shown in AI Studio | Prompts may be used to improve Google's models outside the EEA, UK and Switzerland |
| Groq | gpt-oss-120b/20b, Qwen; 30 requests/min, 1,000/day, 8,000 tokens/min per model; Whisper | Fastest; the small per-minute token limit means long prompts move to the next provider |
| NVIDIA NIM | Nemotron 3 Super, Kimi, GLM, DeepSeek and more; about 40 requests/min per model | NVIDIA Developer account; meant for development and evaluation |
| Mistral | Free Experiment plan | Requests may be used for training unless you opt out |
| OpenRouter | Models ending in `:free`; 50 requests/day (1,000 after a one-time $10 top-up) | Free routes rotate |
| Cerebras, GitHub Models | Trial credit / low daily limits | |

Web search: Tavily (1,000 searches a month free), Brave ($5 monthly credit, card required), Serper (2,500 once), your own SearXNG, or DuckDuckGo without a key. Speech to text uses Groq's free Whisper.

## Deploying

`docker compose up -d` runs everything in one container on port 8000; set `OMNIDOC_AUTH=user:password` before exposing it. [deploy/README.md](deploy/README.md) covers a free Oracle Cloud Always Free VM with automatic HTTPS, an instant Cloudflare tunnel from your computer, and other hosts.

## Use from Claude, Cursor and other MCP clients

```bash
claude mcp add omnidoc -- python /path/to/OmniDoc/mcp_server.py      # Claude Code
```

Claude Desktop (`claude_desktop_config.json`): `{"mcpServers": {"omnidoc": {"command": "python", "args": ["/path/to/OmniDoc/mcp_server.py"]}}}`. Tools: `list_documents`, `search_documents`, `ask`, `read_document`, `extract_fields`, `find_sensitive_data`, `compare_documents`. The server must be running (`OMNIDOC_API_URL`, and `OMNIDOC_API_AUTH` when it has a password). The REST API is documented at `/docs`.

## Configuration

Model and search keys are listed in [`.env.example`](.env.example). Other settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OMNIDOC_MODEL` | first configured provider, else `qwen2.5:7b-instruct` | Default model spec (`gemini:gemini-2.5-flash`, `groq:openai/gpt-oss-120b`, or an Ollama name); switchable in the app |
| `OMNIDOC_LLM_PROVIDERS` | `gemini,groq,nvidia,mistral,cerebras,openrouter,github,custom` | Fallback order of hosted providers |
| `OMNIDOC_LOCAL_FALLBACK` / `OMNIDOC_CLOUD_FALLBACK` | `1` / `0` | Fall back from hosted models to Ollama / from Ollama to hosted models |
| `OMNIDOC_EMBED_MODEL` | Ollama `nomic-embed-text`, else a hosted embedding model, else `st:intfloat/multilingual-e5-small` on the CPU | Changing it re-indexes the library in the background |
| `OMNIDOC_UNDERSTANDING` | `auto` | `auto`: model call only when it helps; `llm`: always; `rules`: never |
| `OMNIDOC_MAX_LLM_CALLS` / `OMNIDOC_MAX_SECONDS` | `8` / `180` | Per-question budget for optional steps |
| `OMNIDOC_WEB_SEARCH` | `auto` | `auto`, `on` or `off` (the interface can override per question) |
| `OMNIDOC_AUTO_EXTRACT` | `1` | Fill the detected type's template after upload |
| `OMNIDOC_VISION_MODEL` | Gemini when configured, else the first installed of `qwen3.5:9b`, `gemma4:12b`, `qwen2.5vl:7b` | Model that reads figures |
| `OMNIDOC_DATA_DIR` | `./.data` | Database, indexes, graph, uploads, caches |
| `OMNIDOC_AUTH` | none | `user:password` required from every visitor (deployments; use HTTPS) |
| `OMNIDOC_GRAPH_CHUNKS` | `40` | Passages per document used for graph extraction (four per model call) |
| `OMNIDOC_SUMMARIES` | `1` | Summarize documents after upload |
| `OMNIDOC_OCR_LANGS` / `OMNIDOC_OCR_DPI` / `OMNIDOC_OCR_MIN_CONF` | detected / `200` / `55` | OCR languages, resolution and word confidence |
| `OMNIDOC_WHISPER_MODEL` | `whisper-large-v3-turbo` | Speech-to-text model (Groq), or `OMNIDOC_WHISPER_BASE_URL` for another endpoint |
| `OMNIDOC_MAX_UPLOAD_MB` | `100` | Upload size limit |
| `OMNIDOC_HOST` / `OMNIDOC_PORT` | `127.0.0.1` / `8000` | API address |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama address |

## Project layout

```text
server.py              FastAPI: profiles, conversations, streaming answers, documents and viewer, records,
                       sensitive data, comparison, extraction, web pages, search, graph, export, the built app
mcp_server.py          MCP server (stdio) over the REST API
core/                  LangGraph workflow, state, pipeline (ingestion and questions), streaming channel
agents/                understanding, context memory, multilingual, planner, supervisor, entity resolution,
                       query expansion, hybrid search, document intelligence, graph, vision, structured data
                       and tables (SQL), summaries, web search, temporal reasoning, evidence, conflicts, math,
                       charts, synthesis, extraction, document types, validation, comparison, model providers
guardrails/            input guard, intent, semantic NLU, execution budget, output verification, sentence checks
retrieval/             LanceDB store, embeddings, reranker, SQLite tables and library records
graph/                 Kùzu store, schema, triple extraction
parsing/               PDF/Word/spreadsheet/slide/e-mail/EPUB/HTML/recording parsing, OCR, transcription,
                       tables, highlighting, sensitive data, safe web reading
frontend/              React 19 + TypeScript: chat, viewer, library, extract, compare, knowledge globe
deploy/                deployment guide, HTTPS (Caddy) compose file
tests/                 API, viewer, agents, providers and export tests
```

## Tests

```bash
pytest tests/test_grounding.py tests/test_document_intelligence.py tests/test_intelligence_layer.py \
       tests/test_server_endpoints.py tests/test_report_compiler.py      # no model calls
pytest tests/test_viewer_endpoints.py                                   # uploads: needs Ollama embeddings
pytest tests/test_agentic_rag_full.py                                   # calls the local model
cd frontend && npx tsc -p tsconfig.app.json --noEmit && npx oxlint src && npm run build
```

The API tests run against a temporary data folder and never touch `.data/`. Hosted providers are tested against a local fake API server.

## Evaluation

`evaluation/` runs a few hand-written questions as a smoke test; its numbers are not benchmark results. Public benchmarks that fit OmniDoc include OmniDocBench and olmOCR-Bench (parsing), MultiHop-RAG and FinanceBench (cited QA), GraphRAG-Bench (graph retrieval), MMLongBench-Doc and UniDoc-Bench (long multimodal documents), ViDoRe v3 (visual retrieval) and RAGTruth (hallucination detection).

## Privacy

With Ollama, inference, embeddings, figure reading, storage and export all stay on your machine. With hosted APIs, the question and the selected passages are sent to the provider you configured (read its data terms; some free tiers may train on prompts); the documents themselves stay in your data folder. Web search sends the search query to the search provider and fetches the result pages from your server; page addresses on private networks are refused. Sessions use opaque tokens and conversations are private to the profile that created them.

## License

MIT
