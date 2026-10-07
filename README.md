# 🎓 OmniDoc — Enterprise Agentic Graph RAG & Document Intelligence

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Kùzu DB](https://img.shields.io/badge/graph-Kùzu_DB-purple.svg)](https://kuzudb.com)
[![LanceDB](https://img.shields.io/badge/vectors-LanceDB-green.svg)](https://lancedb.com)
[![Docling](https://img.shields.io/badge/parser-IBM_Docling-red.svg)](https://github.com/DS4SD/docling)
[![Privacy-First](https://img.shields.io/badge/privacy-100%25_local_offline-success.svg)](#)

**OmniDoc** is an advanced, local-first **Agentic Graph RAG (Retrieval-Augmented Generation)** and document intelligence platform. It transforms unstructured enterprise documents (PDFs, DOCX, complex financial reports, technical manuals) into structured knowledge graphs and hybrid vector indices, executing natural language queries through collaborative multi-agent reasoning, deterministic mathematical sandboxing, and strict groundedness guardrails.

---

## 🌟 Key Capabilities

- **Layout-Aware Document Parsing:** Employs **IBM Docling** to extract document layout ASTs, headers, hierarchical reading order, complex tables, and embedded figures.
- **Dual-Engine Hybrid Storage:**
  - **Knowledge Graph (Kùzu):** Embedded Cypher property graph modeling document hierarchy, chunks, and extracted entity-relation triples.
  - **Hybrid Vector + Lexical Search (LanceDB):** Dense vector similarity (`nomic-embed-text`) + Tantivy BM25 full-text keyword retrieval.
  - **Neural Cross-Encoder Reranker:** Re-scores and compresses top-k candidates before LLM ingestion.
- **Collaborative Multi-Agent Architecture (LangGraph):**
  - **Context & Memory Agent:** Multi-turn conversational context tracking and anaphora resolution (e.g., resolving pronouns like *"them"*, *"it"*, *"that"*).
  - **Query Planner & Supervisor:** Decomposes complex user goals into dynamic DAG plan steps with dependency tracking.
  - **Mathematical Reasoning Agent:** Sandboxed Python runtime (SymPy & NumPy) computing exact financial formulas (CAGR, margin changes, statistics) without LLM arithmetic hallucination.
  - **Data Visualization Agent:** Synthesizes interactive Plotly chart specifications directly from document tables.
  - **Conflict & Discrepancy Resolution:** Audits cross-document contradictions and reports discrepancies with explicit rationales.
  - **Temporal Reasoning Agent:** Reconstructs chronological event timelines and handles versioned document facts.
  - **Multilingual Agent:** Automatic language detection and cross-lingual translation.
  - **Cited Synthesis Agent:** Generates grounded answers with strict citation superscripts and inline LaTeX equations.
- **Enterprise Multi-Layer Guardrails:**
  - **Zero-Keyword Semantic NLU:** Deep intent and constraint extraction without rigid keyword lists.
  - **Input Scope & Adversarial Guard:** Blocks prompt injections, malicious jailbreaks, and off-topic requests.
  - **Execution Budget Guard:** Enforces step and token limits to prevent infinite cyclic reflection loops.
  - **Output Groundedness & NLI Guard:** Natural Language Inference verification scoring factual alignment between answer and evidence.
- **Enterprise Persistence:** Dual PostgreSQL persistence with automatic zero-configuration SQLite fallback.

---

## 🏛️ System Architecture

```text
                                  User Query
                                      │
                                      ▼
                       ┌─────────────────────────────┐
                       │  Input & Adversarial Guard  │
                       └──────────────┬──────────────┘
                                      ▼
                       ┌─────────────────────────────┐
                       │  Context & Memory Resolver  │ (Anaphora resolution)
                       └──────────────┬──────────────┘
                                      ▼
                       ┌─────────────────────────────┐
                       │     Dynamic DAG Planner     │
                       └──────────────┬──────────────┘
                                      ▼
                    ┌───────────────────────────────────┐
                    │    Supervisor Orchestrator        │
                    └───┬─────────────┬─────────────┬───┘
                        │             │             │
        ┌───────────────┴────┐ ┌──────┴──────┐ ┌────┴────────────────┐
        │  Hybrid Retrieval  │ │ Graph RAG   │ │ Multimodal Vision   │
        │ (LanceDB + Tantivy)│ │ (Kùzu Graph)│ │ (MPS / GPU Fallback)│
        └───────────────┬────┘ └──────┬──────┘ └────┬────────────────┘
                        └─────────────┼─────────────┘
                                      ▼
                       ┌─────────────────────────────┐
                       │ Neural Evidence Compression │
                       └──────────────┬──────────────┘
                                      ▼
                        Specialized Reasoning Agents
                        ├─ Mathematical Reasoning (SymPy / NumPy)
                        ├─ Data Visualization (Interactive Plotly)
                        ├─ Conflict & Discrepancy Resolution
                        └─ Temporal Event Timeline Ordering
                                      │
                                      ▼
                       ┌─────────────────────────────┐
                       │    Cited Synthesis Agent    │ (Citations + LaTeX)
                       └──────────────┬──────────────┘
                                      ▼
                       ┌─────────────────────────────┐
                       │   NLI Output Guardrail      │ (Hallucination audit)
                       └──────────────┬──────────────┘
                                      ▼
                           Streamlit Dashboard UI
```

---

## 🗂️ Project Structure

```text
OmniDoc/
├── agents/                       # Specialized LangGraph task agents
│   ├── context_memory_agent.py   # Multi-turn conversational memory & pronoun resolution
│   ├── query_planner.py          # Dynamic DAG plan generator with step dependencies
│   ├── supervisor.py             # DAG execution monitor and router
│   ├── hybrid_agent.py           # LanceDB dense vector + BM25 retrieval agent
│   ├── graph_agent.py            # Kùzu property graph Cypher traversal agent
│   ├── math_agent.py             # Deterministic SymPy/NumPy math execution runtime
│   ├── visualization_agent.py    # Plotly interactive chart synthesis agent
│   ├── conflict_resolution_agent.py # Cross-source contradiction analysis agent
│   ├── temporal_reasoning_agent.py  # Chronological ordering and timeline agent
│   ├── evidence_selection_agent.py  # Neural compression and reranking agent
│   ├── entity_resolution_agent.py   # Canonical entity linking agent
│   ├── query_expansion_agent.py     # Sub-query and synonym expansion
│   ├── structured_data_agent.py     # Read-only SQL and table extraction
│   ├── vision_agent.py              # Multimodal image and figure analysis
│   └── synthesis_agent.py           # Cited synthesis with LaTeX and chart links
├── core/                         # Orchestration & State Contracts
│   ├── state.py                  # Pydantic schemas, agent state, evidence packages
│   ├── workflow.py               # LangGraph compiled cyclic state machine
│   └── pipeline.py               # End-to-end coordinator (Ingestion + Querying)
├── graph/                        # Embedded Property Graph
│   ├── schema.py                 # Cypher DDL (Documents, Chunks, Entities, Triples)
│   ├── store.py                  # Embedded Kùzu database client
│   └── extractor.py              # LLM triple extraction pipeline
├── retrieval/                    # Hybrid Retrieval Engine
│   ├── lancedb_store.py          # LanceDB vector + Tantivy BM25 full-text store
│   ├── reranker.py               # Neural cross-encoder chunk reranker
│   └── embeddings.py             # Local embedding service (`nomic-embed-text`)
├── guardrails/                   # Security, NLU & Verification
│   ├── semantic_nlu.py           # Zero-keyword query intent & constraint extractor
│   ├── input_guard.py            # Prompt injection and scope auditor
│   ├── intent_classifier.py      # Multi-label capability mapper
│   ├── execution_guard.py        # Loop budget and token guard
│   └── output_guard.py           # NLI groundedness verifier & LaTeX repair
├── parsing/                      # Layout-Aware Document Ingestion
│   └── docling_parser.py         # IBM Docling AST parser & chunker
├── db/                           # Persistence Layer
│   └── connection.py             # PostgreSQL connection pool with SQLite fallback
├── evaluation/                   # SOTA Benchmark Harness
│   ├── eval_harness.py           # Automated evaluation harness
│   ├── benchmark_dataset.json    # Standard benchmark query suite
│   └── run_benchmarks.py         # Evaluation CLI runner
├── tests/                        # Regression & Verification Test Suites
│   ├── test_agentic_rag_full.py  # Unit and multi-agent capability tests
│   └── test_full_pipeline_query.py # End-to-end workflow DAG query test
├── app.py                        # Streamlit dashboard orchestrator
├── chat_ui.py                    # Streamlit chat component
├── requirements.txt              # Production dependency specifications
└── PROJECT_AUDIT.md              # Technical audit and architectural capability matrix
```

---

## ⚡ Quick Start

### 1. Prerequisites
- **Python 3.9+** (recommended: Python 3.11 / 3.12)
- **[Ollama](https://ollama.ai)** installed and running locally

### 2. Pull Required Models
```bash
ollama serve

# LLM for multi-agent reasoning & synthesis
ollama pull qwen2.5:7b-instruct

# High-performance local embedding model
ollama pull nomic-embed-text
```

### 3. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/muditagrawal03/OmniDoc.git
cd OmniDoc

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 4. Launch the Dashboard
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

---

## 🧪 Testing & Evaluation

### Run Multi-Agent Capability Tests
```bash
python -m unittest tests/test_agentic_rag_full.py
```

### Run End-to-End Pipeline DAG Query
```bash
python tests/test_full_pipeline_query.py
```

### Run SOTA Benchmark Evaluation Harness
```bash
python evaluation/run_benchmarks.py
```
*Generates automated groundedness, faithfulness, latency (P50/P95), and guardrail rejection metrics saved to `evaluation/benchmark_report.json`.*

---

## 🔒 Privacy & Security

OmniDoc is designed for enterprise confidentiality:
- **Zero Third-Party Cloud Dependencies:** Embeddings, graph storage, vector indexing, and LLM inference operate strictly on your local machine or self-hosted server.
- **Air-Gapped Compatible:** Can run completely offline without an active internet connection.
- **Strict Data Sanitization:** Input guardrails strip prompt injections and dangerous execution sequences prior to agent reasoning.

---

## 📄 License
This project is open-source under the MIT License.
