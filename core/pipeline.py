"""
OmniDoc Agentic Pipeline Coordinator.
Bridges Docling document ingestion, LanceDB hybrid indexing,
Kùzu property graph construction, and LangGraph multi-agent querying.
"""
import os
import re
import shutil
import logging
import threading
from typing import Dict, Any, List, Optional, Iterator, Tuple

from parsing.docling_parser import DoclingParser, ParsedDocument
from graph.store import KuzuGraphStore
from graph.extractor import GraphExtractor
from retrieval.embeddings import EmbeddingService
from retrieval.lancedb_store import LanceDBStore
from retrieval.reranker import ChunkReranker

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
from core.workflow import OmniDocWorkflow

logger = logging.getLogger("OmniDoc.Pipeline")

# How many chunks per document feed LLM triple extraction (each is one LLM call).
GRAPH_CHUNK_LIMIT = int(os.environ.get("OMNIDOC_GRAPH_CHUNKS", "40"))


class AgenticGraphRAGPipeline:
    """End-to-end coordinator for ingestion and LangGraph multi-agent execution."""

    def __init__(self, data_dir: str = ".data", model_name: str = "qwen2.5:7b-instruct"):
        self.data_dir = data_dir
        self.model_name = model_name
        os.makedirs(data_dir, exist_ok=True)

        # 1. Stores & Parsers
        self.figures_dir = os.path.join(data_dir, "figures")
        self.parser = DoclingParser(extracted_images_dir=self.figures_dir)
        self.graph_store = KuzuGraphStore(db_path=os.path.join(data_dir, "kuzu_db", "graph.kuzu"))
        self.extractor = GraphExtractor(self.graph_store, model_name=model_name)
        self.embed_service = EmbeddingService()
        self.lance_store = LanceDBStore(db_dir=os.path.join(data_dir, "lancedb"))
        self.reranker = ChunkReranker()

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
        self.entity_resolution_agent = EntityResolutionAgent(model_name=model_name)
        self.query_expansion_agent = QueryExpansionAgent(model_name=model_name)
        self.graph_agent = GraphAgent(self.graph_store)
        self.hybrid_agent = HybridRetrievalAgent(self.embed_service, self.lance_store, self.reranker)
        self.vision_agent = VisionAgent(images_dir=self.figures_dir)
        self.evidence_selection_agent = EvidenceSelectionAgent(self.reranker)
        self.conflict_resolution_agent = ConflictResolutionAgent(model_name=model_name)
        self.math_agent = MathematicsAgent(model_name=model_name)
        self.visualization_agent = VisualizationAgent(model_name=model_name)
        self.synthesis_agent = SynthesisAgent(model_name=model_name)

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
            visualization_agent=self.visualization_agent
        )

        # Background knowledge-graph extraction progress, keyed by doc_id
        self.graph_jobs: Dict[str, Dict[str, Any]] = {}
        self._graph_lock = threading.Lock()

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

        # 3. Compute Embeddings & Store in LanceDB
        if parsed_doc.chunks:
            texts = [c.text for c in parsed_doc.chunks]
            embeddings = self.embed_service.embed_texts(texts)
            self.lance_store.add_chunks(parsed_doc.chunks, embeddings)

        # 4. Extract entities & relations into the knowledge graph. This is one LLM
        # call per chunk, so by default it runs in the background and reports progress.
        chunks = list(parsed_doc.chunks[:GRAPH_CHUNK_LIMIT])
        if background_graph:
            self.graph_jobs[doc_id] = {"status": "queued", "processed": 0, "total": len(chunks)}
            threading.Thread(
                target=self._extract_graph, args=(doc_id, chunks), name=f"graph-{doc_id}", daemon=True
            ).start()
        else:
            self._extract_graph(doc_id, chunks)

        return parsed_doc

    def _extract_graph(self, doc_id: str, chunks: List[Any]) -> None:
        job = self.graph_jobs.setdefault(doc_id, {"processed": 0, "total": len(chunks)})
        if job.get("status") == "cancelled":
            return
        job["status"] = "running"
        logger.info(f"Extracting knowledge graph triples from {len(chunks)} chunks of {doc_id}...")

        def cancelled() -> bool:
            if job.get("status") != "cancelled":
                return False
            # The document was deleted while a chunk was in flight; drop anything
            # written after the delete.
            self.graph_store.delete_document(doc_id)
            return True

        try:
            # One extraction at a time keeps the local LLM responsive for queries.
            with self._graph_lock:
                for i, ch in enumerate(chunks, start=1):
                    if cancelled():
                        return
                    try:
                        self.extractor.extract_and_index_chunk(
                            doc_id=doc_id,
                            chunk_id=ch.chunk_id,
                            chunk_text=ch.text,
                            page_number=ch.page_number,
                            section_title=ch.section_title or "General"
                        )
                    except Exception as e:
                        logger.warning(f"Triple extraction failed for {ch.chunk_id}: {e}")
                    job["processed"] = i
                if cancelled():
                    return
            job["status"] = "done"
        except Exception as e:
            logger.error(f"Graph extraction for {doc_id} failed: {e}", exc_info=True)
            job["status"] = "failed"

    def cancel_graph_job(self, doc_id: str) -> None:
        job = self.graph_jobs.get(doc_id)
        if job and job.get("status") in ("queued", "running"):
            job["status"] = "cancelled"

    def delete_document(self, doc_id: str) -> None:
        """Removes a document's vectors, graph entities and saved figures."""
        self.cancel_graph_job(doc_id)
        self.lance_store.delete_document(doc_id)
        self.graph_store.delete_document(doc_id)
        if re.fullmatch(r"[A-Za-z0-9_\-.]+", doc_id or ""):
            shutil.rmtree(os.path.join(self.figures_dir, doc_id), ignore_errors=True)

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
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Iterator[Tuple[str, Dict[str, Any]]]:
        """Like query(), but yields ("step", info) per agent and finally ("result", state)."""
        return self.workflow.execute_stream(
            user_query=user_query,
            document_ids=document_ids or [],
            session_id=session_id,
            conversation_history=conversation_history or []
        )
