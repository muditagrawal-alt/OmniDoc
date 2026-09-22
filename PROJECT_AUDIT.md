# PROJECT_AUDIT.md — OmniDoc Technical Audit

**Audit date:** 2026-08-14  
**Auditor:** Automated deep-dive (Antigravity)  
**Scope:** Every file in the repo at commit `9f01235` (HEAD of `main`)

---

## 1. Overview

OmniDoc is a **local, privacy-first document Q&A system** built with Streamlit. It accepts PDF and DOCX uploads, extracts text and images, builds a RAG (Retrieval-Augmented Generation) index using local Ollama models, and lets users query documents through a chat interface. A web search fallback (DuckDuckGo) was added in the most recent commit.

**One-line summary:** Single-user Streamlit app → document upload → text + image extraction → chunking → embedding (Ollama `nomic-embed-text`) → cosine similarity retrieval → LLM generation (Ollama `mistral`) → chat UI with persistent SQLite history.

---

## 2. Architecture & Stack

### 2.1 Repository Map

```
OmniDoc/
├── app.py              # 430 LOC — Main Streamlit entry point, orchestrator
├── rag.py              # 128 LOC — Chunking, embedding, retrieval pipeline
├── db_store.py         # 189 LOC — SQLite persistence (chats, docs, search history)
├── image_loader.py     # 219 LOC — PDF/DOCX image extraction + BLIP captioning + semantic image search
├── web_search.py       #  90 LOC — DuckDuckGo web search integration
├── router.py           #  71 LOC — Intent → handler routing with system prompts
├── blip_caption.py     #  62 LOC — Standalone BLIP captioning CLI (not imported by app.py)
├── intent.py           #  58 LOC — LLM-based intent classification (3 categories)
├── chat_ui.py          #  47 LOC — Streamlit chat rendering component
├── loader.py           #  35 LOC — PDF/DOCX text extraction
├── llm.py              #  16 LOC — Ollama chat wrapper
├── requirements.txt    #  25 lines — Pinned + unpinned deps
├── README.md           # 109 lines
├── .gitignore          #  26 lines
│
├── .data/omnidoc.db    # 40 KB — SQLite database (currently empty — 0 rows in all 5 tables)
├── .cache/             # 0 B  — Embedding cache dirs exist but are empty
├── extracted_images/   # ~10 MB — 17 PNG files extracted from a test PDF
├── test_docs/          # ~32 MB — 3 test PDFs
├── test_pictures/      # ~36 KB — 4 test images (JPEG/PNG)
├── untitled folder/    # ~4.7 MB — Project documentation (SRS, Summary, Update .docx) + a research paper PDF
└── .venv/              # Virtual environment (not tracked)
```

**Source:** `find` + `wc -l *.py` + `du -sh` on disk.

### 2.2 Full Tech Stack

| Layer | Technology | Version / Spec | Source |
|---|---|---|---|
| **Language** | Python 3 | Not pinned (no `python-requires`) | Inferred from code |
| **UI Framework** | Streamlit | `>=1.28.0` | requirements.txt L16 |
| **LLM Runtime** | Ollama (local) | `>=0.6.1` (Python client) | requirements.txt L9 |
| **LLM Model** | `mistral:latest` | Via Ollama | llm.py L3, intent.py L4 |
| **Embedding Model** | `nomic-embed-text` | Via Ollama | rag.py L9, image_loader.py L24 |
| **Image Captioning** | Salesforce BLIP (`blip-image-captioning-base`) | Via HuggingFace `transformers >=4.35.0` | image_loader.py L11, requirements.txt L22 |
| **Deep Learning** | PyTorch | `>=2.0.0` | requirements.txt L23 |
| **PDF Parsing** | PyMuPDF (fitz) | `==1.22.5` (pinned) | requirements.txt L14 |
| **DOCX Parsing** | python-docx | `==0.8.11` (pinned) | requirements.txt L15 |
| **Image Processing** | Pillow | `>=10.0.0` | requirements.txt L21 |
| **Numerical** | NumPy | `>=1.24.0` | requirements.txt L24 |
| **Database** | SQLite 3 | Stdlib | db_store.py L2 |
| **Vector Store** | Custom in-memory (Python lists + cosine sim) | N/A | rag.py L23-L122 |
| **Embedding Cache** | Pickle files on disk | N/A | rag.py L10 |
| **Web Search** | DuckDuckGo Instant Answer API | Free, no key | web_search.py L22 |
| **HTTP Client** | `requests` | `>=2.31.0` | requirements.txt L20 |

**Declared but unused in production code:**
- `sentence-transformers >=2.5.1` — requirements.txt L17 — Not imported anywhere in current source. Likely a leftover from early experimentation before switching to Ollama embeddings.
- `faiss-cpu >=1.10.2` — requirements.txt L18 — Not imported anywhere. The README mentions "Persistent vector store (FAISS / Chroma)" as a planned improvement.
- `chromadb >=0.4.0` — requirements.txt L19 — Not imported anywhere.
- `uuid6 >=1.0.0` — requirements.txt L25 — stdlib `uuid` is used instead (app.py L8).

**No deployment/infra tooling found:** No Dockerfile, docker-compose, Procfile, pyproject.toml, setup.py, Makefile, CI/CD config (.github/workflows), or .env files exist in the repo.

### 2.3 Entry Points

| Entry Point | How to Run | Source |
|---|---|---|
| **Main App** | `streamlit run app.py` | README.md L99 |
| **BLIP Caption CLI** | `python blip_caption.py` (prompts for folder) | blip_caption.py L56-L63 |
| **Intent Test CLI** | `python intent.py` (runs 3 hardcoded test prompts) | intent.py L50-L59 |

---

## 3. End-to-End Pipeline Trace

### 3.1 Document Ingestion Pipeline

```
User uploads PDF/DOCX via Streamlit
       │
       ▼
[app.py L192-L265] — File bytes read, MD5 hash computed for caching
       │
       ├── Text Extraction
       │   └── [loader.py] load_uploaded_document()
       │       ├── PDF → fitz.open() → page.get_text() per page
       │       └── DOCX → Document() → paragraph.text joined
       │
       ├── Image Extraction (parallel track)
       │   └── [image_loader.py]
       │       ├── PDF → extract_images_with_captions() using fitz
       │       │   ├── Per image: deduplicate by MD5 hash
       │       │   ├── Caption via BLIP (BlipForConditionalGeneration, max_new_tokens=50)
       │       │   └── Embed caption via Ollama nomic-embed-text
       │       └── DOCX → extract_images_from_docx() via python-docx relationships
       │           └── Same caption + embed flow
       │
       ├── RAG Index Construction
       │   └── [rag.py] RAGPipeline.ingest()
       │       ├── Chunking: word-level split, chunk_size=500, overlap=100
       │       ├── Check pickle cache (.cache/embeddings/{doc_hash}.pkl)
       │       ├── If miss: embed each chunk via Ollama nomic-embed-text
       │       └── Store embeddings in Python list (in-memory)
       │
       └── DB Registration
           └── [db_store.py] add_document() → SQLite documents table
```

### 3.2 Query Pipeline

```
User types query in chat input
       │
       ▼
[app.py L317-L423]
       │
       ├── Intent Detection
       │   └── [intent.py] detect_intent() — Ollama mistral:latest
       │       └── Returns one of: question_answering, summarization, information_extraction
       │
       ├── RAG Retrieval
       │   └── [rag.py] RAGPipeline.retrieve(query, top_k=5)
       │       ├── Embed query via Ollama nomic-embed-text
       │       └── Cosine similarity against all chunk embeddings (brute-force)
       │
       ├── Routing
       │   └── [router.py] route()
       │       ├── If retrieved_chunks: use top-k chunks as context
       │       ├── Else: pass full document text
       │       ├── If use_web_search AND query matches keyword list:
       │       │   └── [web_search.py] DuckDuckGo API call (timeout=5s)
       │       └── Call [llm.py] call_llm(prompt, system) — Ollama mistral:latest
       │           └── temperature=0.2, num_ctx=8192
       │
       ├── Image Retrieval
       │   └── [image_loader.py] find_relevant_images_semantic(query, images, top_k=2)
       │       └── Cosine similarity on caption embeddings, threshold > 0.3
       │
       └── Display + Persist
           ├── Render response, images, web sources in Streamlit
           └── Save to SQLite: message + search_history tables
```

### 3.3 Key Parameters (Hardcoded)

| Parameter | Value | Source |
|---|---|---|
| Chunk size | 500 words | rag.py L26 |
| Chunk overlap | 100 words | rag.py L26 |
| Retrieval top-k | 5 | app.py L355 |
| Image retrieval top-k | 2 | app.py L372 |
| Image relevance threshold | 0.3 (cosine sim) | image_loader.py L91 |
| LLM temperature | 0.2 | llm.py L13 |
| LLM context window | 8192 tokens | llm.py L14 |
| BLIP max_new_tokens | 50 | image_loader.py L39 |
| Web search timeout | 5 seconds | web_search.py L31 |
| Web search max results | 3 (passed from router) | router.py L54 |
| Document hash algorithm | MD5 | app.py L196 |

---

## 4. My Contributions vs. Existing Code

### 4.1 Contributor Breakdown

| Author | Commits | Notes |
|---|---|---|
| **Mudit Agrawal** (`muditagrawal03@gmail.com`) | 43 | All substantive code |
| **VS Code** (`vscode@users.noreply.github.com`) | 3 | Automated VS Code session checkpoints (turn 0/1/2) from 2026-06-05 |

**Source:** `git shortlog -sn --all`

### 4.2 Mudit Agrawal's Commit Timeline

**Date range:** 2026-01-13 to 2026-06-05 (~5 months, with most activity in Jan 2026)

| Phase | Date Range | Commits | Key Changes |
|---|---|---|---|
| **Project Init** | Jan 13, 2026 | 7 commits | Empty file scaffolding, .gitignore, intent classification, router, loader, Streamlit UI, requirements |
| **RAG Integration** | Jan 14-16, 2026 | 8 commits | sentence-transformers, faiss-cpu, embeddings, chunking, retrieval engine, RAG pipeline, RAG in UI |
| **RAG Optimization** | Jan 19, 2026 | 3 commits | Optimised RAG, updated pipeline, "Fixed Hallucinations" |
| **Image Pipeline** | Jan 20-22, 2026 | 10 commits | BLIP model testing, image extraction from PDFs, captioning, DOCX image support, UI integration, README |
| **Chat Persistence** | Jan 23-28, 2026 | 4 commits | Chat history, conversations, revert cycle |
| **Web Search** | Jun 5, 2026 | 1 commit | DuckDuckGo API integration |

**Source:** `git log --format="%ai|%s" --all`

### 4.3 VS Code Session Commits

3 commits on 2026-06-05 (`c21ad4a`, `8bdb06c`, `8b80803`) are automated VS Code checkpoints. The final one (`8b80803`) shows 19 files changed with 1,058 insertions and 418 deletions — this appears to be a large refactor/rewrite session that restructured the codebase (added `db_store.py`, `chat_ui.py`, `web_search.py`; deleted `pipeline.py`, `vector_store.py`, `temp_pdf.py`, `retriever.py`).

**Source:** `git show 8b80803 --stat`

### 4.4 Deleted Files Over Time

Files that existed at some point but were removed during refactoring:

| File | Purpose (inferred from name/commits) |
|---|---|
| `pipeline.py` | Original CLI pipeline runner |
| `vector_store.py` | Early vector store wrapper |
| `retriever.py` | Separate retrieval module |
| `chunker.py` | Standalone chunking module |
| `embeddings.py` | Standalone embedding module |
| `executor.py` | Task executor |
| `image_extractor.py` | Early image extraction (replaced by `image_loader.py`) |
| `blip_download.py` | BLIP model download script |
| `blip_test.py` | BLIP testing script |
| `temp_pdf.py` | Temporary PDF handling |

**Source:** `git log --all --diff-filter=D --name-only`

**Conclusion: 100% of the code was written by Mudit Agrawal.** The 3 VS Code commits are automated checkpoints of Mudit's own work session, not contributions from another person.

---

## 5. Quantifiable Findings

### 5.1 Scale

| Metric | Value | Source |
|---|---|---|
| Total Python source files | 11 | `find *.py` |
| Total Python LOC (current) | 1,345 | `wc -l *.py` |
| Git total lines added (all time) | 4,472 | `git log --numstat` sum |
| Git total lines removed (all time) | 1,454 | `git log --numstat` sum |
| Total commits | 46 (43 Mudit + 3 VS Code) | `git shortlog -sn --all` |
| Extracted images on disk | 17 PNG files, ~10 MB total | `extracted_images/` directory listing |
| Test documents on disk | 3 PDFs, ~32 MB total | `test_docs/` directory (files: `testing doc.pdf` 29MB, `Osmansagar CDSE-Report-27.11.2025.pdf` 3.4MB, `sad1109Jaco5p.indd.pdf` 1.5MB) |
| Test images on disk | 4 files, ~36 KB | `test_pictures/` |
| Project documentation | 3 DOCX + 1 PDF (~4.7 MB) | `untitled folder/` (SRS, Summary, Update docs + `2402.06196v3.pdf` research paper) |
| SQLite database size | 40 KB | `.data/omnidoc.db` |
| SQLite database tables | 5 (documents, chats, messages, vector_metadata, search_history) | `sqlite3 .tables` |
| SQLite records (all tables) | 0 | `SELECT COUNT(*)` on each table — all return 0 |
| Embedding cache files | 0 | `.cache/embeddings/` and `.cache/image_embeddings/` directories exist but are empty |
| Number of services/endpoints | 1 (Streamlit app) | Single `app.py` entry point |
| Supported file formats | 2 (PDF, DOCX) | loader.py L29-L33 |
| Intent categories | 3 (question_answering, summarization, information_extraction) | intent.py L11-L13 |
| Web search keywords tracked | 21 | web_search.py L82-L86 |

### 5.2 Performance

**No performance metrics (latency, throughput, p50/p95, tokens/sec, docs/sec) are recorded anywhere in the repo.** No benchmark scripts, timing decorators, profiling output, or performance logs exist.

The only performance-adjacent signal:
- Embedding progress logging prints every 10 chunks: `"  {i + 1}/{len(self.chunks)} chunks embedded"` — rag.py L87-L88. This logs to stdout but is not persisted or timestamped.

### 5.3 Quality

**No quality metrics (accuracy, F1, precision, recall) are recorded anywhere in the repo.** There are:

- No test files (no `test_*.py`, no `conftest.py`, no pytest/unittest configuration)
- No evaluation scripts or notebooks
- No model comparison results
- No retrieval quality benchmarks
- No golden answer sets

The `intent.py` file has a `__main__` block with 3 hardcoded test prompts (intent.py L50-L59) — but this is a manual smoke test, not an automated evaluation. It produces no recorded output.

The commit message `"Fixed Hallucinations"` (commit `7a68557`, 2026-01-19) suggests hallucination was observed and addressed, but no before/after measurements exist.

### 5.4 Production / Reliability Signals

**No production deployment evidence found.** Specifically:

- No CI/CD configuration (.github/workflows, Jenkinsfile, etc.)
- No Dockerfile or container config
- No environment variable files (.env)
- No monitoring/alerting setup
- No log aggregation
- No health check beyond the Ollama connectivity check (app.py L78-L107)
- The SQLite database has 0 records in all tables, indicating the persisted database has been wiped or never used in a sustained session

**Error handling present but basic:**
- All modules use try/except with `print()` to stderr — not structured logging
- `app.py` has a debug mode toggle (L69-L70) that shows tracebacks in the UI
- No retry logic on Ollama calls (single-shot, fail with warning)
- Web search has a 5-second timeout (web_search.py L31)

### 5.5 Efficiency Gains

**No efficiency metrics are documented in the repo.** No before/after comparisons, time savings calculations, cost analysis, or error-rate reduction data exist in code, comments, README, or commit messages.

### 5.6 Codebase Footprint Summary

| Metric | Value |
|---|---|
| Python source files | 11 |
| Total Python LOC | 1,345 |
| Largest file | `app.py` (430 LOC) |
| Smallest file | `llm.py` (16 LOC) |
| Non-code files in repo | README.md, requirements.txt, .gitignore |
| Test files | 0 |
| Test coverage configuration | None |
| Automated tests | 0 |
| CI/CD pipelines | 0 |

---

## 6. Architecture Notes & Observations

### 6.1 Vector Store is In-Memory Only
The RAG pipeline stores embeddings as a Python list in the `RAGPipeline` instance (rag.py L30). Retrieval is brute-force cosine similarity over all chunks (rag.py L115-L121). FAISS and ChromaDB are declared in requirements but never used. The README acknowledges this as a planned improvement (README.md L90).

### 6.2 Dual Cosine Similarity Implementations
- `rag.py` L13-L20: Pure Python implementation (no numpy)
- `image_loader.py` L83-L90: NumPy-based implementation

Both compute cosine similarity but use different approaches.

### 6.3 Embedding Model Used Twice
The same `nomic-embed-text` model is loaded/called independently in both `rag.py` (L9) and `image_loader.py` (L24) — no shared utility.

### 6.4 BLIP Caption Module Duplication
`blip_caption.py` is a standalone CLI script that loads and runs BLIP captioning. `image_loader.py` has its own BLIP loading and captioning code. `blip_caption.py` is not imported by `app.py` or any other module — it appears to be an earlier experiment that was kept.

### 6.5 `vector_metadata` Table Unused
The `vector_metadata` table is created in the schema (db_store.py L65-L75) but no code ever inserts into it. There is no `add_vector_metadata()` method.

### 6.6 Web Search Keyword Detection
The `should_use_web_search()` method (web_search.py L77-L90) includes "2024" and "2025" as trigger keywords but not "2026" (the current year at the time of the latest commit).

---

## 7. Gaps — Things That Would Need Separate Measurement or Confirmation

| Gap | What's missing | Why it matters |
|---|---|---|
| **Latency numbers** | No timing on embed, retrieve, or generate calls | Can't characterize user-facing response time |
| **Throughput** | No measurement of docs/sec ingestion or queries/sec | Can't assess scalability |
| **Retrieval quality** | No golden QA pairs, no precision@k or recall@k measurement | Can't assess RAG accuracy |
| **Intent classification accuracy** | Only 3 manual test prompts in `intent.py`, no labeled dataset | Can't assess classification reliability |
| **BLIP caption quality** | No evaluation of caption accuracy vs. actual image content | Can't assess image understanding contribution to RAG |
| **Embedding quality** | No comparison between `nomic-embed-text` and alternatives (sentence-transformers, etc.) | Can't assess if the embedding model is optimal |
| **Max document size** | No testing at scale — `num_ctx=8192` limits effective context | Unknown behavior on documents > ~6000 words |
| **Chunk parameter tuning** | chunk_size=500 and overlap=100 are hardcoded with no documented rationale | Might not be optimal |
| **Concurrent user behavior** | SQLite + Streamlit session state — no locking | Unknown behavior with multiple simultaneous users |
| **BLIP model load time** | Model loads at import time (image_loader.py L15-L22) — cold start penalty unknown | Could be significant on first request |
| **Dependency security** | No `pip audit` or vulnerability scanning | 4 unused heavy deps (faiss, chromadb, sentence-transformers, uuid6) increase attack surface |
| **Test coverage** | Zero tests | No regression protection |
| **Production usage data** | Database is empty (0 rows all tables), cache is empty | Either never deployed for sustained use, or data was cleared |
