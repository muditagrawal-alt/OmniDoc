"""
OmniDoc Agentic Pipeline Coordinator.
Bridges Docling document ingestion, LanceDB hybrid indexing,
Kùzu property graph construction, and LangGraph multi-agent querying.
"""
import os
import re
import json
import time
import shutil
import logging
import threading
from typing import Dict, Any, Callable, List, Optional, Iterator, Tuple

from parsing.docling_parser import DoclingParser, ParsedDocument
from graph.store import KuzuGraphStore
from graph.extractor import GraphExtractor
from retrieval.embeddings import EmbeddingService
from retrieval.lancedb_store import LanceDBStore
from retrieval.reranker import ChunkReranker
from retrieval.table_store import TableStore

from guardrails.input_guard import InputGuardrail
from guardrails.output_guard import OutputGuardrail
from guardrails.execution_guard import ExecutionBudgetGuard
from guardrails.semantic_nlu import SemanticNLU
from guardrails.intent_classifier import IntentClassifierAgent

from agents.context_memory_agent import ContextMemoryAgent
from agents.query_planner import QueryPlanner
from agents.supervisor import SupervisorAgent
from agents.entity_resolution_agent import EntityResolutionAgent
from agents.query_expansion_agent import QueryExpansionAgent
from agents.graph_agent import GraphAgent
from agents.hybrid_agent import HybridRetrievalAgent
from agents.vision_agent import VisionAgent
from agents.evidence_selection_agent import EvidenceSelectionAgent
from agents.conflict_resolution_agent import ConflictResolutionAgent
from agents.math_agent import MathematicsAgent
from agents.visualization_agent import VisualizationAgent
from agents.synthesis_agent import SynthesisAgent
from agents.table_agent import TableQAAgent
from agents.summary_agent import DocumentSummarizer, CorpusSummaryAgent
from agents.extraction_agent import SchemaExtractionAgent, PRESETS, TYPE_PRESETS, normalise_fields
from agents.understanding_agent import QueryUnderstandingAgent
from agents.multilingual_agent import MultilingualAgent
from agents.document_intelligence_agent import DocumentIntelligenceAgent
from agents.temporal_reasoning_agent import TemporalReasoningAgent
from agents.structured_data_agent import StructuredDataAgent
from agents.doc_classifier import classify
from agents.web_search_agent import WebSearchAgent
from agents.validation import validate
from agents import llm_providers
from retrieval.records import LibraryRecords
from core.workflow import OmniDocWorkflow

logger = logging.getLogger("OmniDoc.Pipeline")

# How many chunks per document feed LLM triple extraction (each is one LLM call).
GRAPH_CHUNK_LIMIT = int(os.environ.get("OMNIDOC_GRAPH_CHUNKS", "40"))
# Summarise every uploaded document in the background (a few LLM calls per document).
SUMMARIES_ENABLED = os.environ.get("OMNIDOC_SUMMARIES", "1") != "0"
# Fill the template of a recognised document type (invoice, contract, ...) after upload (one or two calls).
AUTO_EXTRACT = os.environ.get("OMNIDOC_AUTO_EXTRACT", "1") != "0"
# Describe the pages that are mostly pictures or charts with the vision model, and index the
# descriptions, so questions about maps, infographics and photos find their pages.
FIGURE_CAPTIONS = os.environ.get("OMNIDOC_FIGURE_CAPTIONS", "1") != "0"


def contextual_text(title: str, section: str, text: str, overview: str = "") -> str:
    """
    The text a passage is embedded and keyword-indexed with: its document, section and (once
    the document is summarised) a one-line overview of the document, then the passage. A
    passage that says "the company grew 12%" can then be found by the company's name.
    """
    head = title or ""
    if section and section != "General" and not section.startswith("Page "):
        head += f" — {section}"
    if overview:
        head += f"\n{overview}"
    return f"{head}\n{text}" if head else text
_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-.]+$")


class AgenticGraphRAGPipeline:
    """End-to-end coordinator for ingestion and LangGraph multi-agent execution."""

    def __init__(self, data_dir: Optional[str] = None, model_name: Optional[str] = None):
        data_dir = data_dir or os.getenv("OMNIDOC_DATA_DIR") or ".data"
        self.data_dir = data_dir
        model_name = model_name or llm_providers.default_spec()
        self.model_name = model_name
        os.makedirs(data_dir, exist_ok=True)

        # 1. Stores & Parsers
        self.figures_dir = os.path.join(data_dir, "figures")
        self.parser = DoclingParser(extracted_images_dir=self.figures_dir)
        self.graph_store = KuzuGraphStore(db_path=os.path.join(data_dir, "kuzu_db", "graph.kuzu"))
        self.extractor = GraphExtractor(self.graph_store, model_name=model_name)
        self.embed_service = EmbeddingService(cache_dir=os.path.join(data_dir, "cache", "embeddings"))
        self.lance_store = LanceDBStore(db_dir=os.path.join(data_dir, "lancedb"))
        self.reranker = ChunkReranker()
        self.table_store = TableStore(os.path.join(data_dir, "tables.db"))
        self.layout_dir = os.path.join(data_dir, "layout")
        self.page_cache_dir = os.path.join(data_dir, "page_cache")
        os.makedirs(self.layout_dir, exist_ok=True)
        self.records = LibraryRecords(self.table_store, os.path.join(data_dir, "records"))
        # Set by the server: {doc_id: display title}, and the library's document rows.
        self.doc_title_provider: Optional[Callable[[], Dict[str, str]]] = None
        self.doc_list_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None

        # 2. Guardrails & Semantic NLU
        self.input_guard = InputGuardrail(model_name=model_name)
        self.output_guard = OutputGuardrail(model_name=model_name)
        self.execution_guard = ExecutionBudgetGuard()
        self.semantic_nlu = SemanticNLU(model_name=model_name)
        self.intent_classifier = IntentClassifierAgent(model_name=model_name)

        # 3. Agents
        self.context_memory_agent = ContextMemoryAgent(model_name=model_name)
        self.query_planner = QueryPlanner(model_name=model_name)
        self.supervisor = SupervisorAgent(model_name=model_name)
        self.entity_resolution_agent = EntityResolutionAgent(model_name=model_name, graph_store=self.graph_store)
        self.query_expansion_agent = QueryExpansionAgent(model_name=model_name)
        self.graph_agent = GraphAgent(self.graph_store)
        self.hybrid_agent = HybridRetrievalAgent(self.embed_service, self.lance_store, self.reranker)
        self.vision_agent = VisionAgent(images_dir=self.figures_dir)
        self.evidence_selection_agent = EvidenceSelectionAgent(self.reranker)
        self.conflict_resolution_agent = ConflictResolutionAgent(model_name=model_name)
        self.math_agent = MathematicsAgent(model_name=model_name)
        self.visualization_agent = VisualizationAgent(model_name=model_name)
        self.synthesis_agent = SynthesisAgent(model_name=model_name)
        self.table_agent = TableQAAgent(self.table_store, model_name=model_name,
                                        embed=lambda texts: self.embed_service.embed_texts(texts, kind="query"))
        self.understanding_agent = QueryUnderstandingAgent(model_name=model_name)
        self.multilingual_agent = MultilingualAgent()
        self.document_intelligence_agent = DocumentIntelligenceAgent(self.lance_store)
        self.temporal_agent = TemporalReasoningAgent(model_name=model_name)
        self.structured_data_agent = StructuredDataAgent(self.table_agent)
        self.web_search_agent = WebSearchAgent(self.reranker, cache_dir=os.path.join(data_dir, "web_cache"))
        self.summarizer = DocumentSummarizer(os.path.join(data_dir, "summaries"), model_name=model_name)
        self.corpus_agent = CorpusSummaryAgent(self.summarizer, self.lance_store, doc_titles=self.document_titles)
        self.extraction_agent = SchemaExtractionAgent(self.hybrid_agent, self.lance_store, model_name=model_name)

        # 4. LangGraph Multi-Agent Workflow
        self.workflow = OmniDocWorkflow(
            input_guard=self.input_guard,
            output_guard=self.output_guard,
            supervisor=self.supervisor,
            graph_agent=self.graph_agent,
            hybrid_agent=self.hybrid_agent,
            vision_agent=self.vision_agent,
            synthesis_agent=self.synthesis_agent,
            execution_guard=self.execution_guard,
            context_memory_agent=self.context_memory_agent,
            semantic_nlu=self.semantic_nlu,
            intent_classifier=self.intent_classifier,
            query_planner=self.query_planner,
            entity_resolution_agent=self.entity_resolution_agent,
            query_expansion_agent=self.query_expansion_agent,
            evidence_selection_agent=self.evidence_selection_agent,
            conflict_resolution_agent=self.conflict_resolution_agent,
            math_agent=self.math_agent,
            visualization_agent=self.visualization_agent,
            table_agent=self.table_agent,
            corpus_agent=self.corpus_agent,
            understanding_agent=self.understanding_agent,
            multilingual_agent=self.multilingual_agent,
            document_intelligence_agent=self.document_intelligence_agent,
            temporal_agent=self.temporal_agent,
            structured_data_agent=self.structured_data_agent,
            web_search_agent=self.web_search_agent,
        )

        # Background knowledge-graph extraction progress, keyed by doc_id
        self.graph_jobs: Dict[str, Dict[str, Any]] = {}
        self._graph_lock = threading.Lock()
        self.reindex_status: Dict[str, Any] = {"status": "idle"}
        self._check_index()

    # ------------------------------------------------------------------ index
    INDEX_VERSION = 2  # 2: chunks embedded with document / section context

    def _index_meta_path(self) -> str:
        return os.path.join(self.data_dir, "index_meta.json")

    def _check_index(self) -> None:
        """Re-indexes in the background when the embedding model or the indexing scheme changed."""
        try:
            with open(self._index_meta_path(), "r", encoding="utf-8") as f:
                stored = json.load(f)
        except (OSError, ValueError):
            stored = {}
        current = {"embed_model": self.embed_service.model_name, "version": self.INDEX_VERSION}
        if os.path.exists(self._backup_path()):
            logger.info("Resuming an interrupted re-index.")
            threading.Thread(target=self.reindex, name="reindex", daemon=True).start()
            return
        has_rows = bool(self.lance_store.document_ids())
        if not has_rows:
            self._write_index_meta(current)
            return
        if stored.get("embed_model") == current["embed_model"] and stored.get("version") == current["version"]:
            return
        logger.info(f"Index was built with {stored or 'an older version'}; re-indexing with {current} in the background.")
        threading.Thread(target=self.reindex, name="reindex", daemon=True).start()

    def _write_index_meta(self, meta: Dict[str, Any]) -> None:
        tmp = self._index_meta_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        os.replace(tmp, self._index_meta_path())

    def _backup_path(self) -> str:
        return os.path.join(self.data_dir, "reindex_backup.json")

    def reindex(self) -> None:
        """Re-embeds every document's chunks (new embedding model or contextual text); no model calls."""
        from core.state import RetrievedChunk
        self.reindex_status = {"status": "running", "processed": 0, "total": 0}
        try:
            if os.path.exists(self._backup_path()):
                with open(self._backup_path(), "r", encoding="utf-8") as f:
                    saved = {d: [RetrievedChunk(**c) for c in rows] for d, rows in json.load(f).items()}
            else:
                saved = {d: self.lance_store.get_document_chunks(d) for d in self.lance_store.document_ids()}
            self.reindex_status["total"] = len(saved)
            titles = self.document_titles()
            probe = self.embed_service.embed_texts(["dimension probe"])[0]
            if self.lance_store.vector_dim() not in (None, len(probe)) or not self.lance_store.has_search_text:
                # New vector size or schema: keep a copy of the passages, then rebuild the table.
                tmp = self._backup_path() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({d: [c.model_dump() for c in rows] for d, rows in saved.items()}, f)
                os.replace(tmp, self._backup_path())
                self.lance_store.drop_all()
            for i, (doc_id, chunks) in enumerate(saved.items(), 1):
                summary = self.summarizer.load(doc_id) or {}
                first = re.split(r"(?<=[.!?])\s+", (summary.get("summary") or "").strip(), maxsplit=1)[0][:240]
                if chunks:
                    self._index_chunks(titles.get(doc_id, doc_id), chunks, first)
                self.reindex_status.update(processed=i)
            self._write_index_meta({"embed_model": self.embed_service.model_name, "version": self.INDEX_VERSION})
            if os.path.exists(self._backup_path()):
                os.remove(self._backup_path())
            self.reindex_status["status"] = "done"
            logger.info(f"Re-indexed {len(saved)} document(s).")
        except Exception as e:
            logger.error(f"Re-indexing failed: {e}", exc_info=True)
            self.reindex_status["status"] = "failed"

    def document_titles(self) -> Dict[str, str]:
        """{doc_id: title} for every indexed document (library titles when the server provides them)."""
        if self.doc_title_provider is not None:
            try:
                return dict(self.doc_title_provider())
            except Exception:
                pass
        return {d: d for d in self.lance_store.document_ids()}

    # ------------------------------------------------------------------ layout
    def _layout_path(self, doc_id: str, meta: bool = False) -> str:
        return os.path.join(self.layout_dir, f"{doc_id}{'.meta' if meta else ''}.json")

    def _save_layout(self, parsed: ParsedDocument, doc_type: Optional[Dict[str, Any]] = None) -> None:
        """Page sizes, chunk / table boxes and OCR words (for highlighting), plus a small summary."""
        if not _SAFE_ID.match(parsed.doc_id or ""):
            return
        meta = {
            "pages": len(parsed.layout.get("pages", [])),
            "ocr_pages": parsed.ocr_pages,
            "ocr_languages": parsed.ocr_languages,
            "tables": len(parsed.tables),
            "figures": len(parsed.visual_elements),
            "doc_type": (doc_type or {}).get("type", "other"),
            "doc_type_label": (doc_type or {}).get("label", "Document"),
            "doc_type_confidence": (doc_type or {}).get("confidence", 0.0),
            "media": parsed.layout.get("media"),
        }
        for path, payload in ((self._layout_path(parsed.doc_id), parsed.layout),
                              (self._layout_path(parsed.doc_id, meta=True), meta)):
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)

    def layout(self, doc_id: str) -> Dict[str, Any]:
        if not _SAFE_ID.match(doc_id or ""):
            return {}
        try:
            with open(self._layout_path(doc_id), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def layout_meta(self, doc_id: str) -> Dict[str, Any]:
        if not _SAFE_ID.match(doc_id or ""):
            return {}
        try:
            with open(self._layout_path(doc_id, meta=True), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def set_model(self, model_name: str) -> None:
        """Switches every LLM-backed component to another local Ollama model."""
        self.model_name = model_name
        for component in list(vars(self).values()):
            if hasattr(component, "model_name") and component is not self:
                try:
                    setattr(component, "model_name", model_name)
                except Exception:
                    pass
        logger.info(f"Pipeline model switched to {model_name}")


    def ingest_document(
        self,
        file_path: str,
        doc_id: str,
        doc_hash: str,
        fast_mode: bool = False,
        background_graph: bool = False,
        title: Optional[str] = None,
    ) -> ParsedDocument:
        """
        Parses document via Docling or fast PyMuPDF, indexes chunks into LanceDB,
        and extracts entities and relations into Kùzu. `title` is the name shown to
        users (the uploaded filename); it defaults to the stored file's name.
        """
        logger.info(f"Starting Agentic Graph RAG ingestion for {file_path} (ID: {doc_id}, fast_mode={fast_mode})")
        
        # 1. Parse via Docling or PyMuPDF JIT
        parsed_doc = self.parser.parse_document(file_path, doc_id=doc_id, fast_mode=fast_mode)
        
        # 2. Register Document in Kùzu
        display_title = title or parsed_doc.filename
        self.graph_store.add_document(
            doc_id=doc_id,
            title=display_title,
            doc_type=display_title.rsplit(".", 1)[-1].lower(),
            doc_hash=doc_hash
        )

        # 3. Embeddings with document and section context, stored in LanceDB
        if parsed_doc.chunks:
            self._index_chunks(display_title, parsed_doc.chunks)

        # 4. Document type (no model call), page layout (for citation highlights), tables (for SQL)
        opening = " ".join(c.text for c in parsed_doc.chunks[:4])[:6000]
        doc_type = classify(opening, display_title, display_title.rsplit(".", 1)[-1].lower() if "." in display_title else "")
        logger.info(f"{doc_id} looks like: {doc_type['label']} ({doc_type['confidence']})")
        try:
            self._save_layout(parsed_doc, doc_type)
        except Exception as e:
            logger.warning(f"Could not save layout for {doc_id}: {e}")
        try:
            stored = self.table_store.add_tables(doc_id, parsed_doc.tables)
            if stored:
                logger.info(f"Stored {stored} table(s) of {doc_id} for SQL questions.")
        except Exception as e:
            logger.warning(f"Could not store tables of {doc_id}: {e}")

        self.refresh_records()

        # 5. Summary, extraction of the type's fields, then entities & relations for the knowledge
        # graph. All are model calls, so by default they run in the background with progress.
        if background_graph:
            self.graph_jobs[doc_id] = {"status": "queued", "stage": "summary", "processed": 0, "total": 0}
            threading.Thread(
                target=self._post_ingest, args=(doc_id, display_title, list(parsed_doc.chunks)),
                name=f"ingest-{doc_id}", daemon=True,
            ).start()
        else:
            self._post_ingest(doc_id, display_title, list(parsed_doc.chunks))

        return parsed_doc

    def _index_chunks(self, title: str, chunks: List[Any], overview: str = "") -> None:
        """Embeds chunks with their document/section context (and overview) and stores them."""
        search_texts = [contextual_text(title, c.section_title or "", c.text, overview) for c in chunks]
        embeddings = self.embed_service.embed_texts(search_texts)
        self.lance_store.add_chunks(chunks, embeddings, search_texts=search_texts)

    def _contextualize(self, doc_id: str, title: str, chunks: List[Any]) -> None:
        """Re-indexes a document's chunks with the first sentence of its summary as context."""
        summary = self.summarizer.load(doc_id) or {}
        first = re.split(r"(?<=[.!?])\s+", (summary.get("summary") or "").strip(), maxsplit=1)[0][:240]
        if first and chunks:
            self._index_chunks(title, chunks, first)

    def _describe_figures(self, doc_id: str, title: str, progress: Optional[Any] = None) -> int:
        """
        Indexes a description of each page that is mostly pictures or charts (one vision call per
        page, at most OMNIDOC_CAPTION_MAX_PAGES), as a passage of that page. Returns how many.
        """
        from core.state import RetrievedChunk
        path = self.vision_agent._upload(doc_id)
        if not path:
            return 0
        captions = self.vision_agent.caption_pages(path, title, progress=progress)
        if not captions:
            return 0
        chunks = [RetrievedChunk(chunk_id=f"{doc_id}_p{page}_fig", doc_id=doc_id, page_number=page,
                                 text=f"Description of the pictures and charts on page {page}: {text}",
                                 section_title=f"Figures on page {page}", score=0.0, retrieval_method="hybrid")
                  for page, text in captions]
        summary = self.summarizer.load(doc_id) or {}
        first = re.split(r"(?<=[.!?])\s+", (summary.get("summary") or "").strip(), maxsplit=1)[0][:240]
        self._index_chunks(title, chunks, first)
        logger.info(f"Indexed descriptions of {len(chunks)} picture page(s) of {doc_id}.")
        return len(chunks)

    def _auto_extract(self, doc_id: str, title: str) -> None:
        """Fills the template of the document's type and checks the values (one or two model calls)."""
        meta = self.layout_meta(doc_id)
        doc_type = meta.get("doc_type") or "other"
        preset = TYPE_PRESETS.get(doc_type)
        if not (AUTO_EXTRACT and preset) or self.records.load(doc_id):
            return
        fields = normalise_fields(PRESETS[preset]["fields"])
        result = self.extraction_agent.extract(doc_id, title, fields)
        checks = validate(doc_type, result["fields"])
        self.records.save(doc_id, {
            "doc_id": doc_id, "title": title, "doc_type": doc_type, "label": meta.get("doc_type_label"),
            "template": preset, "fields": result["fields"], "sources": result["sources"], "validation": checks,
            "extracted_at": time.time(),
        })
        self.refresh_records()

    def library_documents(self) -> List[Dict[str, Any]]:
        """The library's documents with page, OCR, table, type and summary facts (for the record tables)."""
        rows = []
        try:
            docs = self.doc_list_provider() if self.doc_list_provider else [{"id": d, "filename": t} for d, t in self.document_titles().items()]
        except Exception:
            docs = []
        for d in docs:
            meta = self.layout_meta(d["id"])
            rows.append({"id": d["id"], "title": d.get("filename") or d["id"], "file_type": d.get("file_type"),
                         "upload_date": d.get("upload_date"), "size_bytes": d.get("size_bytes"), "pages": meta.get("pages"),
                         "ocr_pages": len(meta.get("ocr_pages") or []), "tables": meta.get("tables", 0),
                         "doc_type": meta.get("doc_type"), "has_summary": self.summarizer.has(d["id"])})
        return rows

    def backfill_types(self) -> int:
        """Detects the type of documents uploaded before type detection existed (no model calls)."""
        done = 0
        for doc_id, title in self.document_titles().items():
            meta = self.layout_meta(doc_id)
            if meta.get("doc_type") or not _SAFE_ID.match(doc_id or ""):
                continue
            chunks = self.lance_store.get_document_chunks(doc_id)[:4]
            if not chunks:
                continue
            found = classify(" ".join(c.text for c in chunks)[:6000], title, title.rsplit(".", 1)[-1].lower() if "." in title else "")
            meta.update(doc_type=found["type"], doc_type_label=found["label"], doc_type_confidence=found["confidence"])
            path = self._layout_path(doc_id, meta=True)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(meta, f)
            os.replace(path + ".tmp", path)
            done += 1
        if done:
            logger.info(f"Detected the type of {done} earlier document(s).")
        return done

    def refresh_records(self) -> None:
        try:
            self.records.refresh(self.library_documents())
        except Exception as e:
            logger.warning(f"Could not refresh the library records: {e}")

    def _post_ingest(self, doc_id: str, title: str, chunks: List[Any]) -> None:
        """Background work after upload: summary, contextual re-index, figure descriptions, extraction, knowledge graph."""
        job = self.graph_jobs.setdefault(doc_id, {"processed": 0, "total": 0})
        if job.get("status") == "cancelled":
            return

        def cancelled() -> bool:
            if job.get("status") != "cancelled":
                return False
            # The document was deleted while work was in flight; drop anything written after.
            self.graph_store.delete_document(doc_id)
            self.summarizer.delete(doc_id)
            return True

        try:
            # One job at a time keeps the local LLM responsive for questions; until it is
            # this document's turn the job stays "queued".
            with self._graph_lock:
                if job.get("status") == "cancelled":
                    return
                job["status"] = "running"
                if SUMMARIES_ENABLED and chunks and not self.summarizer.has(doc_id):
                    job.update(stage="summary", processed=0, total=0)

                    def progress(i: int, n: int) -> None:
                        job.update(processed=i, total=n)
                    try:
                        self.summarizer.summarize(doc_id, title, chunks, progress=progress)
                        self._contextualize(doc_id, title, chunks)
                    except Exception as e:
                        logger.warning(f"Summary of {doc_id} failed: {e}")
                    self.refresh_records()
                if cancelled():
                    return
                if FIGURE_CAPTIONS and getattr(self, "vision_agent", None) is not None:
                    job.update(stage="figures", processed=0, total=0)
                    try:
                        self._describe_figures(doc_id, title, lambda i, n: job.update(processed=i, total=n))
                    except Exception as e:
                        logger.warning(f"Figure descriptions for {doc_id} failed: {e}")
                if cancelled():
                    return
                if AUTO_EXTRACT and TYPE_PRESETS.get(self.layout_meta(doc_id).get("doc_type") or ""):
                    job.update(stage="extract", processed=0, total=1)
                    try:
                        self._auto_extract(doc_id, title)
                    except Exception as e:
                        logger.warning(f"Field extraction for {doc_id} failed: {e}")
                    job.update(processed=1)
                if cancelled():
                    return
                graph_chunks = chunks[:GRAPH_CHUNK_LIMIT]
                job.update(stage="graph", processed=0, total=len(graph_chunks))
                logger.info(f"Extracting knowledge graph triples from {len(graph_chunks)} chunks of {doc_id}...")

                def graph_progress(done: int, total: int) -> None:
                    job.update(processed=done, total=total)
                    if job.get("status") == "cancelled":
                        raise InterruptedError("cancelled")
                try:
                    self.extractor.extract_batch(doc_id, graph_chunks, progress=graph_progress)
                except InterruptedError:
                    pass
                if cancelled():
                    return
            job["status"] = "done"
        except Exception as e:
            logger.error(f"Background processing of {doc_id} failed: {e}", exc_info=True)
            job["status"] = "failed"

    def summarize_missing(self, doc_ids: Optional[List[str]] = None) -> List[str]:
        """
        Queues background summaries for documents that have none (uploaded before summaries
        existed, or whose summary failed). Returns the ids queued; they run one at a time.
        """
        titles = self.document_titles()
        busy = {d for d, j in self.graph_jobs.items() if j.get("status") in ("queued", "running")}
        queued = [d for d in (doc_ids or list(titles)) if d in titles and d not in busy and not self.summarizer.has(d)]
        if not queued:
            return []
        previous = {d: self.graph_jobs.get(d) for d in queued}
        for d in queued:
            self.graph_jobs[d] = {"status": "queued", "stage": "summary", "processed": 0, "total": 0}

        def work() -> None:
            for doc_id in queued:
                self._summarize_one(doc_id, titles[doc_id], previous.get(doc_id))

        threading.Thread(target=work, name="summaries", daemon=True).start()
        return queued

    def _summarize_one(self, doc_id: str, title: str, previous_job: Optional[Dict[str, Any]]) -> None:
        job = self.graph_jobs.get(doc_id)
        if job is None or job.get("status") == "cancelled":
            return
        with self._graph_lock:
            job["status"] = "running"
            try:
                chunks = self.lance_store.get_document_chunks(doc_id)
                self.summarizer.summarize(doc_id, title, chunks, progress=lambda i, n: job.update(processed=i, total=n))
            except Exception as e:
                logger.warning(f"Summary of {doc_id} failed: {e}")
        if job.get("status") == "cancelled":
            self.summarizer.delete(doc_id)
        elif previous_job:
            self.graph_jobs[doc_id] = previous_job  # back to the graph extraction status it had
        else:
            self.graph_jobs.pop(doc_id, None)

    def cancel_graph_job(self, doc_id: str) -> None:
        job = self.graph_jobs.get(doc_id)
        if job and job.get("status") in ("queued", "running"):
            job["status"] = "cancelled"

    def delete_document(self, doc_id: str) -> None:
        """Removes a document's vectors, graph entities, tables, summary, layout and saved images."""
        self.cancel_graph_job(doc_id)
        self.lance_store.delete_document(doc_id)
        self.graph_store.delete_document(doc_id)
        self.table_store.delete_document(doc_id)
        self.summarizer.delete(doc_id)
        self.records.delete(doc_id)
        if _SAFE_ID.match(doc_id or ""):
            shutil.rmtree(os.path.join(self.figures_dir, doc_id), ignore_errors=True)
            shutil.rmtree(os.path.join(self.page_cache_dir, doc_id), ignore_errors=True)
            for path in (self._layout_path(doc_id), self._layout_path(doc_id, meta=True)):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def query(
        self,
        user_query: str,
        doc_id: Optional[str] = None,
        document_ids: Optional[List[str]] = None,
        session_id: str = "default_session",
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Executes query through the LangGraph Multi-Agent Workflow.
        """
        if document_ids is not None:
            doc_ids = document_ids
        elif doc_id:
            doc_ids = [doc_id]
        else:
            doc_ids = []

        return self.workflow.execute(
            user_query=user_query,
            document_ids=doc_ids,
            session_id=session_id,
            conversation_history=conversation_history or []
        )

    def query_stream(
        self,
        user_query: str,
        document_ids: Optional[List[str]] = None,
        session_id: str = "default_session",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        web_mode: str = "auto",
    ) -> Iterator[Tuple[str, Dict[str, Any]]]:
        """Like query(), but yields events per agent, streamed answer text, and finally ("result", state)."""
        return self.workflow.execute_stream(
            user_query=user_query,
            document_ids=document_ids or [],
            session_id=session_id,
            conversation_history=conversation_history or [],
            web_mode=web_mode,
        )
