"""
Core state schemas and typed contracts for OmniDoc Advanced Agentic Graph RAG.
Defines Pydantic models for contracts, execution plans, evidence, and the LangGraph workflow state.
"""
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from enum import Enum
import operator
from pydantic import BaseModel, Field


# ============================================================================
# 1. SEMANTIC NLU & QUERY REPRESENTATION
# ============================================================================

class SemanticQuery(BaseModel):
    """
    Structured semantic query representation produced by the Semantic NLU Layer.
    Captures intent, constraints, entities, operations, and ambiguity without keyword heuristics.
    """
    raw_query: str = Field(description="Original user query text")
    resolved_query: str = Field(description="Query with multi-turn anaphora and pronouns resolved")
    goal: str = Field(description="High-level analytical or informational objective")
    task_types: List[str] = Field(default_factory=list, description="List of detected task types (e.g. comparison, calculation, retrieval)")
    entities: List[str] = Field(default_factory=list, description="Extracted named entities or concepts")
    entity_types: Dict[str, str] = Field(default_factory=dict, description="Mapping of entity to type (e.g. Organization, Metric)")
    relationships: List[str] = Field(default_factory=list, description="Explicit relationships mentioned (e.g. acquired, revenue of)")
    attributes: List[str] = Field(default_factory=list, description="Target attributes (e.g. margin, growth rate, CEO)")
    constraints: Dict[str, Any] = Field(default_factory=dict, description="Domain and operational constraints")
    temporal_constraints: Optional[Dict[str, Any]] = Field(default=None, description="Time ranges, intervals (e.g. start: 2020, end: 2024, order: after)")
    numerical_constraints: Optional[Dict[str, Any]] = Field(default=None, description="Thresholds, target values, math constraints")
    geographic_constraints: Optional[Dict[str, Any]] = Field(default=None, description="Locations, regions, countries")
    operations: List[str] = Field(default_factory=list, description="Operations to perform: retrieve, compare, calculate, visualize, explain")
    output_requirements: List[str] = Field(default_factory=list, description="Requested output modalities: narrative, table, chart, code")
    modality_requirements: List[str] = Field(default_factory=list, description="text, visual, tabular, spatial")
    language: str = Field(default="en", description="Detected language code (e.g. en, hi, fr)")
    ambiguity_detected: bool = Field(default=False, description="True if underspecified terms require resolution")
    ambiguity_details: Optional[str] = Field(default=None, description="Explanation of ambiguity")
    sub_questions: List[str] = Field(default_factory=list, description="Decomposed sub-questions for pathfinding")


# ============================================================================
# 2. CONVERSATION CONTEXT & MEMORY STATE
# ============================================================================

class ConversationMemoryState(BaseModel):
    """
    Compact structured conversational memory passed between turns.
    Avoids injecting full raw message history into every prompt.
    """
    active_entities: List[str] = Field(default_factory=list, description="Entities actively discussed in current thread")
    active_time_range: Optional[str] = Field(default=None, description="Active temporal frame")
    active_topic: Optional[str] = Field(default=None, description="Active subject matter or document section")
    previous_queries: List[str] = Field(default_factory=list, description="Recent queries in session")
    previous_results_summary: List[str] = Field(default_factory=list, description="Brief summary of prior turn findings")
    unresolved_references: List[str] = Field(default_factory=list, description="Pronouns or terms requiring resolution")


# ============================================================================
# 3. INTENT CLASSIFICATION RESULT
# ============================================================================

class IntentClassificationResult(BaseModel):
    """
    Multi-label semantic intent classification output.
    """
    primary_intent: str = Field(description="Dominant intent category")
    secondary_intents: List[str] = Field(default_factory=list, description="Co-occurring intents (e.g. calculation + visualization)")
    confidence_scores: Dict[str, float] = Field(default_factory=dict, description="Confidence per detected intent (0.0 to 1.0)")
    detected_requirements: List[str] = Field(default_factory=list, description="Required agent capabilities")
    is_in_scope: bool = Field(default=True, description="True if query is within document analytical scope")
    rejection_reason: Optional[str] = Field(default=None, description="Reason if filtered")
    confidence: float = Field(default=0.85, description="Primary confidence")

    @property
    def requires_graph(self) -> bool:
        return any("graph" in r.lower() for r in self.detected_requirements) or self.primary_intent in ["multi_hop_relational", "entity_network"]

    @property
    def requires_vector(self) -> bool:
        return True

    @property
    def requires_vision(self) -> bool:
        return any("vision" in r.lower() for r in self.detected_requirements) or "multimodal_analysis" in self.secondary_intents

    @property
    def requires_web(self) -> bool:
        return any("web" in r.lower() for r in self.detected_requirements) or "realtime_web" in self.secondary_intents

    @property
    def requires_math(self) -> bool:
        return any("math" in r.lower() for r in self.detected_requirements) or "numerical_calculation" in self.secondary_intents

    @property
    def requires_visualization(self) -> bool:
        return any("visual" in r.lower() or "chart" in r.lower() for r in self.detected_requirements) or "visualization" in self.secondary_intents



# ============================================================================
# 4. QUERY EXECUTION PLAN (DAG)
# ============================================================================

class PlanStep(BaseModel):
    """A single executable step in the Query Planner's DAG."""
    id: str = Field(description="Unique step identifier (e.g. step_1_retrieval)")
    agent: str = Field(description="Target specialized agent name")
    description: str = Field(description="Human-readable step objective")
    depends_on: List[str] = Field(default_factory=list, description="IDs of steps that must complete before this step")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Parameters tailored for the agent")
    fallback_agent: Optional[str] = Field(default=None, description="Optional fallback if primary agent fails")
    status: str = Field(default="pending", description="pending | running | completed | failed | skipped")
    result: Optional[Dict[str, Any]] = None


class QueryExecutionPlan(BaseModel):
    """Machine-readable execution plan generated by the Query Planner."""
    goal: str = Field(description="Synthesized objective")
    execution_mode: str = Field(default="dag", description="dag | single_agent | linear_pipeline")
    steps: List[PlanStep] = Field(default_factory=list, description="Ordered/topological execution steps")
    estimated_complexity: str = Field(default="low", description="low | medium | high")


# ============================================================================
# 5. STANDARDIZED AGENT CONTRACTS
# ============================================================================

class AgentTaskInput(BaseModel):
    """Uniform task envelope passed to any specialized agent."""
    task_id: str
    agent_name: str
    query_id: str
    semantic_query: SemanticQuery
    step_inputs: Dict[str, Any] = Field(default_factory=dict)
    accumulated_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    timeout_seconds: float = 15.0


class AgentTaskOutput(BaseModel):
    """Uniform response envelope returned by any specialized agent."""
    task_id: str
    agent_name: str
    status: str = Field(default="success", description="success | failure | fallback_triggered | partial")
    result_data: Dict[str, Any] = Field(default_factory=dict)
    evidence_produced: List[Dict[str, Any]] = Field(default_factory=list)
    citations_produced: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    execution_time_ms: float = 0.0
    errors: List[str] = Field(default_factory=list)


# ============================================================================
# 6. EVIDENCE & CONFLICT RESOLUTION
# ============================================================================

class EvidenceItem(BaseModel):
    """Atomic unit of retrieved evidence from vector, graph, table, or vision."""
    evidence_id: str
    source_type: str = Field(description="vector_chunk | kg_triple | table_row | vision_element | web")
    source_id: str
    content: str
    relevance_score: float = 1.0
    authority_score: float = 1.0
    timestamp: Optional[str] = None
    provenance: Dict[str, Any] = Field(default_factory=dict, description="doc_id, page_no, chunk_id, etc.")


class EvidencePackage(BaseModel):
    """Ranked, deduplicated, and verified evidence ready for synthesis."""
    query_id: str
    items: List[EvidenceItem] = Field(default_factory=list)
    total_candidates_considered: int = 0
    selected_count: int = 0
    compression_ratio: float = 1.0


class ConflictRecord(BaseModel):
    """Identifies and reconciles contradictory evidence across sources."""
    conflicting_claim: str
    evidence_a: EvidenceItem
    evidence_b: EvidenceItem
    resolution_status: str = Field(description="resolved | unresolved_uncertainty")
    preferred_evidence_id: Optional[str] = None
    rationale: str
    confidence: float = 0.5


# ============================================================================
# 7. MATHEMATICS & VISUALIZATION ARTIFACTS
# ============================================================================

class MathExecutionResult(BaseModel):
    """Exact auditable output from the sandboxed Mathematical Reasoning Agent."""
    task: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    formula: str
    code_executed: str
    exact_result: Any
    units: Optional[str] = None
    assumptions: List[str] = Field(default_factory=list)
    source_evidence_ids: List[str] = Field(default_factory=list)


class VisualizationArtifact(BaseModel):
    """Interactive chart specification emitted by the Visualization Agent."""
    chart_type: str = Field(description="bar | line | scatter | pie | heatmap | map")
    title: str
    plotly_spec: Dict[str, Any] = Field(default_factory=dict, description="Plotly JSON specification")
    underlying_data: List[Dict[str, Any]] = Field(default_factory=list)
    caption: str = ""


# ============================================================================
# 8. LEGACY & GRAPH COMPATIBILITY MODELS (PRESERVED)
# ============================================================================

class QueryIntentType(str, Enum):
    """Preserved for backward compatibility."""
    FACTUAL_LOOKUP = "factual_lookup"
    MULTI_HOP_RELATIONAL = "multi_hop_relational"
    DEEP_SUMMARY = "deep_summary"
    VISUAL_DIAGRAM = "visual_diagram"
    COMPARATIVE_AUDIT = "comparative_audit"
    OUT_OF_SCOPE = "out_of_scope"


class QueryIntentContract(BaseModel):
    """Preserved for backward compatibility."""
    raw_query: str
    refined_query: str
    intent: QueryIntentType
    confidence: float = 0.85
    entities_mentioned: List[str] = Field(default_factory=list)
    sub_questions: List[str] = Field(default_factory=list)
    requires_graph: bool = True
    requires_vector: bool = True
    requires_vision: bool = False
    requires_web: bool = False
    is_in_scope: bool = True
    rejection_reason: Optional[str] = None


class EntityNode(BaseModel):
    id: str
    name: str
    category: str = "Concept"
    description: str = ""
    doc_id: str
    source_chunk_ids: List[str] = Field(default_factory=list)


class RelationshipEdge(BaseModel):
    source_id: str
    target_id: str
    relation: str
    description: str = ""
    weight: float = 1.0
    doc_id: str


class GraphSubGraph(BaseModel):
    nodes: List[EntityNode] = Field(default_factory=list)
    edges: List[RelationshipEdge] = Field(default_factory=list)
    traversal_path: List[str] = Field(default_factory=list)
    community_context: str = ""


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    page_number: int = 1
    section_title: Optional[str] = None
    score: float = 0.0
    retrieval_method: str = "hybrid"


class VisualElement(BaseModel):
    figure_id: str
    doc_id: str
    page_number: int
    caption: str = ""
    image_path: Optional[str] = None
    bounding_box: Optional[List[float]] = None
    visual_analysis: Optional[str] = None


class VerificationResult(BaseModel):
    is_grounded: bool
    faithfulness_score: float = 0.0
    supported_claims: List[str] = Field(default_factory=list)
    unsupported_claims: List[str] = Field(default_factory=list)
    cited_sources: List[str] = Field(default_factory=list)
    action: str = "accept"
    feedback: str = ""


# ============================================================================
# 9. GLOBAL WORKFLOW STATE (LANGGRAPH)
# ============================================================================

class AgentWorkflowState(TypedDict):
    """
    Central LangGraph execution state.
    Tracks query, semantic representation, conversation memory, dynamic plan,
    accumulated multi-agent findings, evidence verification, and final outputs.
    """
    session_id: str
    user_query: str
    document_ids: List[str]
    
    # NLU & Planning
    semantic_query: Optional[SemanticQuery]
    memory_state: Optional[ConversationMemoryState]
    intent_result: Optional[IntentClassificationResult]
    execution_plan: Optional[QueryExecutionPlan]
    
    # Backward-compatible fields
    intent: Optional[QueryIntentContract]
    plan: List[str]
    
    # Multi-Agent Context Accumulators
    graph_context: Annotated[List[Dict[str, Any]], operator.add]
    chunk_context: Annotated[List[Dict[str, Any]], operator.add]
    visual_context: Annotated[List[Dict[str, Any]], operator.add]
    web_context: Annotated[List[Dict[str, Any]], operator.add]
    math_results: Annotated[List[Dict[str, Any]], operator.add]
    visual_artifacts: Annotated[List[Dict[str, Any]], operator.add]
    
    # Evidence & Verification
    evidence_package: Optional[EvidencePackage]
    conflicts: Annotated[List[Dict[str, Any]], operator.add]
    verification: Optional[VerificationResult]
    
    # Outputs & Control
    draft_response: str
    verified_response: str
    iteration_count: int
    max_iterations: int
    errors: Annotated[List[str], operator.add]
    agent_traces: Annotated[List[Dict[str, Any]], operator.add]
    conversation_history: List[Dict[str, str]]
    is_complete: bool
