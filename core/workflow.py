"""
LangGraph Multi-Agent Execution Graph for OmniDoc.
Compiles the stateful cyclic graph with multi-turn context memory, zero-keyword semantic NLU,
multi-label intent classification, dynamic DAG query planning, sandboxed mathematical reasoning,
interactive Plotly visualizations, neural evidence selection, conflict audits, cited synthesis,
and self-healing reflection loops.
"""
import logging
from typing import Dict, Any, Literal, List, Optional
from langgraph.graph import StateGraph, END

from core.state import (
    AgentWorkflowState,
    QueryIntentContract,
    SemanticQuery,
    IntentClassificationResult,
    QueryExecutionPlan,
    VerificationResult
)
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

logger = logging.getLogger("OmniDoc.Workflow")


class OmniDocWorkflow:
    """Orchestrates the Advanced Agentic Graph RAG multi-agent graph with LangGraph."""

    def __init__(
        self,
        input_guard: InputGuardrail = None,
        output_guard: OutputGuardrail = None,
        supervisor: SupervisorAgent = None,
        graph_agent: GraphAgent = None,
        hybrid_agent: HybridRetrievalAgent = None,
        vision_agent: VisionAgent = None,
        synthesis_agent: SynthesisAgent = None,
        execution_guard: ExecutionBudgetGuard = None,
        context_memory_agent: ContextMemoryAgent = None,
        semantic_nlu: SemanticNLU = None,
        intent_classifier: IntentClassifierAgent = None,
        query_planner: QueryPlanner = None,
        entity_resolution_agent: EntityResolutionAgent = None,
        query_expansion_agent: QueryExpansionAgent = None,
        evidence_selection_agent: EvidenceSelectionAgent = None,
        conflict_resolution_agent: ConflictResolutionAgent = None,
        math_agent: MathematicsAgent = None,
        visualization_agent: VisualizationAgent = None,
    ):
        self.input_guard = input_guard or InputGuardrail()
        self.output_guard = output_guard or OutputGuardrail()
        self.supervisor = supervisor or SupervisorAgent()
        self.graph_agent = graph_agent
        self.hybrid_agent = hybrid_agent
        self.vision_agent = vision_agent or VisionAgent()
        self.synthesis_agent = synthesis_agent or SynthesisAgent()
        self.execution_guard = execution_guard or ExecutionBudgetGuard()

        # Advanced Agentic Components
        self.context_memory_agent = context_memory_agent or ContextMemoryAgent()
        self.semantic_nlu = semantic_nlu or SemanticNLU()
        self.intent_classifier = intent_classifier or IntentClassifierAgent()
        self.query_planner = query_planner or QueryPlanner()
        self.entity_resolution_agent = entity_resolution_agent or EntityResolutionAgent()
        self.query_expansion_agent = query_expansion_agent or QueryExpansionAgent()
        self.evidence_selection_agent = evidence_selection_agent or EvidenceSelectionAgent()
        self.conflict_resolution_agent = conflict_resolution_agent or ConflictResolutionAgent()
        self.math_agent = math_agent or MathematicsAgent()
        self.visualization_agent = visualization_agent or VisualizationAgent()

        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentWorkflowState)

        # 1. Register All Agent and Guardrail Nodes
        builder.add_node("context_resolution", self._context_resolution_step)
        builder.add_node("semantic_nlu", self._semantic_nlu_step)
        builder.add_node("intent_classification", self._intent_classification_step)
        builder.add_node("rejection_node", self._rejection_step)
        builder.add_node("query_planner", self._query_planner_step)
        builder.add_node("supervisor", self.supervisor.plan_and_route)
        builder.add_node("entity_resolution", self._entity_resolution_step)
        builder.add_node("query_expansion", self._query_expansion_step)
        builder.add_node("hybrid_retrieval", self.hybrid_agent.run)
        builder.add_node("graph_retrieval", self._graph_retrieval_step)
        builder.add_node("vision_retrieval", self._vision_retrieval_step)
        builder.add_node("evidence_selection", self.evidence_selection_agent.run)
        builder.add_node("conflict_resolution", self.conflict_resolution_agent.run)
        builder.add_node("math_reasoning", self._math_step)
        builder.add_node("visualization", self._visualization_step)
        builder.add_node("synthesis_agent", self.synthesis_agent.synthesize)
        builder.add_node("output_guard", self._output_guard_step)
        builder.add_node("reflection_node", self._reflection_step)

        # 2. Set Entry Point
        builder.set_entry_point("context_resolution")

        # 3. Context Resolution -> Semantic NLU -> Intent Classification
        builder.add_edge("context_resolution", "semantic_nlu")
        builder.add_edge("semantic_nlu", "intent_classification")

        # 4. Conditional Edge: Intent Guardrail Check (In-scope vs Filtered)
        builder.add_conditional_edges(
            "intent_classification",
            self._route_after_intent,
            {
                "proceed": "query_planner",
                "reject": "rejection_node"
            }
        )
        builder.add_edge("rejection_node", END)

        # 5. Query Planner -> Supervisor -> Pre-Retrieval Agents
        builder.add_edge("query_planner", "supervisor")
        builder.add_edge("supervisor", "entity_resolution")
        builder.add_edge("entity_resolution", "query_expansion")
        builder.add_edge("query_expansion", "hybrid_retrieval")

        # 6. Multi-Source Retrieval: Hybrid -> Graph -> Vision
        builder.add_edge("hybrid_retrieval", "graph_retrieval")
        builder.add_edge("graph_retrieval", "vision_retrieval")

        # 7. Post-Retrieval Reasoning: Evidence Selection -> Conflict Resolution
        builder.add_edge("vision_retrieval", "evidence_selection")
        builder.add_edge("evidence_selection", "conflict_resolution")

        # 8. Analytical Agents: Math Reasoning -> Data Visualization
        builder.add_edge("conflict_resolution", "math_reasoning")
        builder.add_edge("math_reasoning", "visualization")

        # 9. Final Synthesis -> Output Groundedness Verification
        builder.add_edge("visualization", "synthesis_agent")
        builder.add_edge("synthesis_agent", "output_guard")

        # 10. Conditional Edge: Groundedness Verification (Accept vs Reflection Loop)
        builder.add_conditional_edges(
            "output_guard",
            self._route_after_output_guard,
            {
                "accept": END,
                "reflect": "reflection_node"
            }
        )

        # 11. Reflection loop routes back to hybrid retrieval for context refinement
        builder.add_edge("reflection_node", "hybrid_retrieval")

        return builder.compile()

    # --- Step Implementations ---

    def _context_resolution_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Resolves conversational anaphora and multi-turn references."""
        history = state.get("conversation_history", [])
        if not history:
            return {}
        return self.context_memory_agent.run(state)


    def _semantic_nlu_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Deep semantic understanding without hardcoded keywords."""
        query = state.get("user_query", "")
        semantic_q = self.semantic_nlu.analyze(query)
        return {"semantic_query": semantic_q}

    def _intent_classification_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Multi-label intent and capability requirement mapping."""
        semantic_q = state.get("semantic_query")
        if not semantic_q:
            semantic_q = self.semantic_nlu.analyze(state.get("user_query", ""))
        
        intent_res = self.intent_classifier.classify(semantic_q)
        
        # Build backward-compatible QueryIntentContract for legacy callers
        from core.state import QueryIntentType
        intent_type = QueryIntentType.FACTUAL_LOOKUP
        if not intent_res.is_in_scope:
            intent_type = QueryIntentType.OUT_OF_SCOPE
        elif intent_res.primary_intent == "multi_hop_relational":
            intent_type = QueryIntentType.MULTI_HOP_RELATIONAL
        elif intent_res.primary_intent in ["comparison", "comparative_audit"]:
            intent_type = QueryIntentType.COMPARATIVE_AUDIT
        elif intent_res.requires_vision:
            intent_type = QueryIntentType.VISUAL_DIAGRAM

        legacy_intent = QueryIntentContract(
            raw_query=state.get("user_query", ""),
            refined_query=semantic_q.resolved_query if semantic_q else state.get("user_query", ""),
            intent=intent_type,
            is_in_scope=intent_res.is_in_scope,
            rejection_reason=intent_res.rejection_reason,
            confidence=intent_res.confidence,
            requires_graph=intent_res.requires_graph,
            requires_vector=intent_res.requires_vector,
            requires_vision=intent_res.requires_vision,
            requires_web=intent_res.requires_web
        )
        return {
            "intent_result": intent_res,
            "intent": legacy_intent
        }


    def _route_after_intent(self, state: AgentWorkflowState) -> Literal["proceed", "reject"]:
        intent_res = state.get("intent_result")
        if intent_res and not intent_res.is_in_scope:
            return "reject"
        return "proceed"

    def _rejection_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        intent_res = state.get("intent_result")
        reason = intent_res.rejection_reason if intent_res else "Query fell outside authorized domain boundaries."
        response = f"🛡️ **OmniDoc Scope Guard:** Your request could not be processed.\n\n*Reason:* {reason}"
        return {
            "verified_response": response,
            "draft_response": response,
            "is_complete": True
        }

    def _query_planner_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Generates dynamic execution plan tailored to semantic requirements."""
        semantic_q = state.get("semantic_query")
        intent_res = state.get("intent_result")
        plan = self.query_planner.generate_plan(semantic_q, intent_res)
        return {
            "execution_plan": plan,
            "plan": [f"{s.agent}: {s.description}" for s in plan.steps]
        }

    def _is_agent_needed(self, state: AgentWorkflowState, agent_names: List[str]) -> bool:
        """Checks whether an agent is explicitly scheduled in the DAG execution plan."""
        exec_plan: Optional[QueryExecutionPlan] = state.get("execution_plan")
        if exec_plan and exec_plan.steps:
            for step in exec_plan.steps:
                if any(name.lower() in step.agent.lower() for name in agent_names):
                    return True
        return False

    def _entity_resolution_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        semantic_q = state.get("semantic_query")
        if (semantic_q and semantic_q.entities) or self._is_agent_needed(state, ["entity_resolution", "entity_resolution_agent"]):
            return self.entity_resolution_agent.run(state)
        return {}

    def _query_expansion_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        if self._is_agent_needed(state, ["query_expansion", "query_expansion_agent"]):
            return self.query_expansion_agent.run(state)
        return {}

    def _graph_retrieval_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        intent_res = state.get("intent_result")
        requires_graph = (intent_res and intent_res.requires_graph) or self._is_agent_needed(state, ["knowledge_graph_agent", "graph_agent", "graph"])
        if requires_graph and self.graph_agent:
            return self.graph_agent.run(state)
        return {}

    def _vision_retrieval_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        intent_res = state.get("intent_result")
        semantic_q = state.get("semantic_query")
        requires_vision = (
            (intent_res and intent_res.requires_vision)
            or (semantic_q and "visual" in semantic_q.modality_requirements)
            or self._is_agent_needed(state, ["vision_agent", "vision", "inspect_visual_diagrams"])
        )
        if requires_vision and self.vision_agent:
            return self.vision_agent.run(state)
        return {}

    def _math_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        intent_res = state.get("intent_result")
        semantic_q = state.get("semantic_query")
        requires_math = (
            (intent_res and intent_res.requires_math)
            or (semantic_q and "calculate" in semantic_q.operations)
            or self._is_agent_needed(state, ["math_agent", "mathematics_agent", "calculate"])
        )
        if requires_math:
            return self.math_agent.run(state)
        return {}

    def _visualization_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        intent_res = state.get("intent_result")
        semantic_q = state.get("semantic_query")
        requires_viz = (
            (intent_res and intent_res.requires_visualization)
            or (semantic_q and "visualize" in semantic_q.operations)
            or (semantic_q and "chart" in semantic_q.output_requirements)
            or self._is_agent_needed(state, ["visualization_agent", "visualize"])
        )
        if requires_viz:
            return self.visualization_agent.run(state)
        return {}

    def _output_guard_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        verification = self.output_guard.verify(
            query=state["user_query"],
            draft_answer=state.get("draft_response", ""),
            retrieved_chunks=state.get("chunk_context", []),
            graph_context=state.get("graph_context", []),
            math_results=state.get("math_results", []),
            visual_artifacts=state.get("visual_artifacts", []),
            conflicts=state.get("conflicts", []),
            evidence_package=state.get("evidence_package")
        )

        verified_resp = state.get("draft_response", "")
        if verification.action == "accept":
            return {
                "verification": verification,
                "verified_response": verified_resp,
                "is_complete": True
            }

        return {"verification": verification}

    def _route_after_output_guard(self, state: AgentWorkflowState) -> Literal["accept", "reflect"]:
        verification = state.get("verification")
        iter_count = state.get("iteration_count", 0)
        max_iters = state.get("max_iterations", 3)

        if not verification or verification.action == "accept" or iter_count >= max_iters:
            return "accept"
        return "reflect"

    def _reflection_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        verification = state.get("verification")
        feedback = verification.feedback if verification else "Insufficient citations or groundedness detected."
        logger.info(f"🔄 Reflection Loop Triggered: {feedback}")
        return {
            "errors": [f"Reflection triggered: {feedback}"]
        }

    def execute(
        self,
        user_query: str,
        document_ids: list = None,
        session_id: str = "default_session",
        conversation_history: list = None
    ) -> Dict[str, Any]:
        """Executes the compiled LangGraph workflow end-to-end."""
        initial_state: AgentWorkflowState = {
            "session_id": session_id,
            "user_query": user_query,
            "document_ids": document_ids or [],
            "semantic_query": None,
            "memory_state": None,
            "intent_result": None,
            "execution_plan": None,
            "intent": None,
            "plan": [],
            "graph_context": [],
            "chunk_context": [],
            "visual_context": [],
            "web_context": [],
            "math_results": [],
            "visual_artifacts": [],
            "evidence_package": None,
            "conflicts": [],
            "draft_response": "",
            "verified_response": "",
            "verification": None,
            "iteration_count": 0,
            "max_iterations": 3,
            "errors": [],
            "agent_traces": [],
            "conversation_history": conversation_history or [],
            "is_complete": False
        }
        return self.graph.invoke(initial_state)

