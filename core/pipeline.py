"""
OmniDoc Agentic Pipeline Coordinator.
Bridges Docling document ingestion, LanceDB hybrid indexing,
Kùzu property graph construction, and LangGraph multi-agent querying.
"""
import os
import logging
from typing import Dict, Any, List, Optional

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


class AgenticGraphRAGPipeline:
    """End-to-end coordinator for ingestion and LangGraph multi-agent execution."""

    def __init__(self, data_dir: str = ".data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        # 1. Stores & Parsers
        self.parser = DoclingParser()
        self.graph_store = KuzuGraphStore(db_path=os.path.join(data_dir, "kuzu_db", "graph.kuzu"))
        self.extractor = GraphExtractor(self.graph_store)
        self.embed_service = EmbeddingService()
        self.lance_store = LanceDBStore(db_dir=os.path.join(data_dir, "lancedb"))
        self.reranker = ChunkReranker()

        # 2. Guardrails & Semantic NLU
        self.input_guard = InputGuardrail()
        self.output_guard = OutputGuardrail()
        self.execution_guard = ExecutionBudgetGuard()
        self.semantic_nlu = SemanticNLU()
        self.intent_classifier = IntentClassifierAgent()

        # 3. Agents
        self.context_memory_agent = ContextMemoryAgent()
        self.query_planner = QueryPlanner()
        self.supervisor = SupervisorAgent()
        self.entity_resolution_agent = EntityResolutionAgent()
        self.query_expansion_agent = QueryExpansionAgent()
        self.graph_agent = GraphAgent(self.graph_store)
        self.hybrid_agent = HybridRetrievalAgent(self.embed_service, self.lance_store, self.reranker)
        self.vision_agent = VisionAgent()
        self.evidence_selection_agent = EvidenceSelectionAgent(self.reranker)
        self.conflict_resolution_agent = ConflictResolutionAgent()
        self.math_agent = MathematicsAgent()
        self.visualization_agent = VisualizationAgent()
        self.synthesis_agent = SynthesisAgent()

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


    def ingest_document(self, file_path: str, doc_id: str, doc_hash: str) -> ParsedDocument:
        """
        Parses document via Docling, indexes chunks into LanceDB,
        and extracts entities and relations into Kùzu.
        """
        logger.info(f"Starting Agentic Graph RAG ingestion for {file_path} (ID: {doc_id})")
        
        # 1. Parse via Docling
        parsed_doc = self.parser.parse_document(file_path, doc_id=doc_id)
        
        # 2. Register Document in Kùzu
        self.graph_store.add_document(
            doc_id=doc_id,
            title=parsed_doc.filename,
            doc_type=parsed_doc.filename.split(".")[-1].lower(),
            doc_hash=doc_hash
        )

        # 3. Compute Embeddings & Store in LanceDB
        if parsed_doc.chunks:
            texts = [c.text for c in parsed_doc.chunks]
            embeddings = self.embed_service.embed_texts(texts)
            self.lance_store.add_chunks(parsed_doc.chunks, embeddings)

        # 4. Extract Entities & Build Knowledge Graph (top representative chunks)
        # To optimize local performance, extract from first 6 key chunks
        sample_chunks = parsed_doc.chunks[:6]
        logger.info(f"Extracting knowledge graph triples from {len(sample_chunks)} key sections...")
        for ch in sample_chunks:
            self.extractor.extract_and_index_chunk(
                doc_id=doc_id,
                chunk_id=ch.chunk_id,
                chunk_text=ch.text,
                page_number=ch.page_number,
                section_title=ch.section_title or "General"
            )

        return parsed_doc

    def query(
        self,
        user_query: str,
        doc_id: Optional[str] = None,
        session_id: str = "default_session",
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Executes query through the LangGraph Multi-Agent Workflow.
        """
        doc_ids = [doc_id] if doc_id else []
        return self.workflow.execute(
            user_query=user_query,
            document_ids=doc_ids,
            session_id=session_id,
            conversation_history=conversation_history or []
        )

