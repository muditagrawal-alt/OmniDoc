"""
LangGraph multi-agent workflow for OmniDoc.

    input guard -> understanding (0-1 model call) -> plan (supervisor + budget)
      -> hybrid search (+ second pass for uncovered parts) -> document intelligence
      -> knowledge graph -> figures -> tables & library records (SQL) -> document summaries
      -> temporal reasoning -> evidence selection -> conflict check -> math -> charts
      -> cited answer (streamed) -> sentence-level check (-> one revision if needed)

A typical question costs two or three model calls (understanding when it helps, writing,
checking); tables, calculations, charts, figures and conflict audits add one each only when
the question needs them and the per-question budget allows. Every node records model usage
under the question's run id.
"""
import time
import uuid
import queue
import logging
import threading
from typing import Dict, Any, Literal, List, Optional, Iterator, Tuple
from langgraph.graph import StateGraph, END

from core.state import (
    AgentWorkflowState,
    QueryIntentContract,
    QueryIntentType,
    QueryExecutionPlan,
)
from core import streaming
from agents import llm_providers
from guardrails.input_guard import InputGuardrail
from guardrails.output_guard import OutputGuardrail
from guardrails.execution_guard import ExecutionBudgetGuard
from guardrails.semantic_nlu import SemanticNLU
from guardrails.intent_classifier import IntentClassifierAgent

from agents.understanding_agent import QueryUnderstandingAgent, split_language_instruction
from agents.context_memory_agent import ContextMemoryAgent
from agents.multilingual_agent import MultilingualAgent
from agents.query_planner import QueryPlanner
from agents.supervisor import SupervisorAgent
from agents.entity_resolution_agent import EntityResolutionAgent
from agents.query_expansion_agent import QueryExpansionAgent
from agents.graph_agent import GraphAgent
from agents.hybrid_agent import HybridRetrievalAgent
from agents.document_intelligence_agent import DocumentIntelligenceAgent
from agents.temporal_reasoning_agent import TemporalReasoningAgent
from agents.structured_data_agent import StructuredDataAgent
from agents.vision_agent import VisionAgent
from agents.evidence_selection_agent import EvidenceSelectionAgent
from agents.conflict_resolution_agent import ConflictResolutionAgent
from agents.math_agent import MathematicsAgent
from agents.visualization_agent import VisualizationAgent
from agents.synthesis_agent import SynthesisAgent
from agents.table_agent import TableQAAgent, asks_about_tables
from agents.summary_agent import CorpusSummaryAgent, is_corpus_question
from agents.web_search_agent import WebSearchAgent
from agents.llm_utils import trace

logger = logging.getLogger("OmniDoc.Workflow")

# Human-readable names for each graph node, shown as live progress in the UI.
NODE_LABELS: Dict[str, str] = {
    "input_guard": "Checking the question",
    "understanding": "Understanding the question",
    "rejection_node": "Checking scope",
    "supervisor": "Planning",
    "hybrid_retrieval": "Searching documents",
    "document_intelligence": "Following references",
    "graph_retrieval": "Traversing the knowledge graph",
    "vision_retrieval": "Reading figures",
    "structured_data": "Querying tables and records",
    "corpus_summary": "Reading document summaries",
    "web_search": "Searching the web",
    "temporal_reasoning": "Ordering events in time",
    "evidence_selection": "Selecting evidence",
    "conflict_resolution": "Checking for conflicting sources",
    "math_reasoning": "Computing",
    "visualization": "Building charts",
    "synthesis_agent": "Writing the answer",
    "output_guard": "Verifying against sources",
    "reflection_node": "Revising unsupported claims",
}


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"1 {word}"
    if word.endswith("y"):
        return f"{n} {word[:-1]}ies"
    return f"{n} {word}s"


def _last_trace(update: Dict[str, Any]) -> str:
    traces = update.get("agent_traces") or []
    return str(traces[-1].get("detail") or "") if traces and isinstance(traces[-1], dict) else ""


def describe_step(node: str, update: Optional[Dict[str, Any]]) -> str:
    """Short factual summary of what a node produced (empty string if nothing notable)."""
    if not update:
        return ""
    try:
        if node in ("understanding", "supervisor", "document_intelligence", "temporal_reasoning", "structured_data",
                    "conflict_resolution", "corpus_summary", "web_search"):
            return _last_trace(update)[:180]
        if node == "hybrid_retrieval":
            return _plural(len(update.get("chunk_context") or []), "passage")
        if node == "graph_retrieval":
            subgraphs = update.get("graph_context") or []
            nodes = sum(len(g.get("nodes", [])) for g in subgraphs if isinstance(g, dict))
            edges = sum(len(g.get("edges", [])) for g in subgraphs if isinstance(g, dict))
            return f"{_plural(nodes, 'entity')}, {_plural(edges, 'relation')}"
        if node == "evidence_selection":
            pkg = update.get("evidence_package")
            items = getattr(pkg, "items", None) or []
            return f"Kept {len(items)}" if items else ""
        if node == "math_reasoning":
            n = len(update.get("math_results") or [])
            return _plural(n, "calculation") if n else ""
        if node == "visualization":
            n = len(update.get("visual_artifacts") or [])
            return _plural(n, "chart") if n else ""
        if node == "vision_retrieval":
            return _last_trace(update)[:160]
        if node == "output_guard":
            v = update.get("verification")
            score = getattr(v, "faithfulness_score", None)
            if score is not None and getattr(v, "cited_sources", None) is not None:
                return f"Faithfulness {float(score):.2f}"
        if node == "reflection_node":
            return str(update.get("reflection_feedback") or "")[:160]
    except Exception:  # descriptions are cosmetic; never break a run
        return ""
    return ""


def _with_run(fn):
    """Records model usage made inside a node under the question's run id."""
    def node(state: AgentWorkflowState) -> Dict[str, Any]:
        llm_providers.set_current_run(state.get("run_id"))
        try:
            return fn(state) or {}
        finally:
            llm_providers.set_current_run(None)
    node.__name__ = getattr(fn, "__name__", "node")
    return node


class OmniDocWorkflow:
    """Orchestrates OmniDoc's agents with LangGraph."""

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
        table_agent: Optional[TableQAAgent] = None,
        corpus_agent: Optional[CorpusSummaryAgent] = None,
        understanding_agent: Optional[QueryUnderstandingAgent] = None,
        multilingual_agent: Optional[MultilingualAgent] = None,
        document_intelligence_agent: Optional[DocumentIntelligenceAgent] = None,
        temporal_agent: Optional[TemporalReasoningAgent] = None,
        structured_data_agent: Optional[StructuredDataAgent] = None,
        web_search_agent: Optional[WebSearchAgent] = None,
    ):
        self.input_guard = input_guard or InputGuardrail()
        self.output_guard = output_guard or OutputGuardrail()
        self.supervisor = supervisor or SupervisorAgent()
        self.graph_agent = graph_agent
        self.hybrid_agent = hybrid_agent
        self.vision_agent = vision_agent or VisionAgent()
        self.synthesis_agent = synthesis_agent or SynthesisAgent()
        self.execution_guard = execution_guard or ExecutionBudgetGuard()
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
        self.table_agent = table_agent
        self.corpus_agent = corpus_agent
        self.understanding_agent = understanding_agent or QueryUnderstandingAgent()
        self.multilingual_agent = multilingual_agent or MultilingualAgent()
        self.document_intelligence_agent = document_intelligence_agent or DocumentIntelligenceAgent()
        self.temporal_agent = temporal_agent or TemporalReasoningAgent()
        self.structured_data_agent = structured_data_agent or (StructuredDataAgent(table_agent) if table_agent else None)
        self.web_search_agent = web_search_agent

        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentWorkflowState)
        nodes = [
            ("input_guard", self._input_guard_step),
            ("understanding", self._understanding_step),
            ("rejection_node", self._rejection_step),
            ("supervisor", self._supervisor_step),
            ("hybrid_retrieval", self.hybrid_agent.run),
            ("document_intelligence", self._document_intelligence_step),
            ("graph_retrieval", self._graph_retrieval_step),
            ("vision_retrieval", self._vision_retrieval_step),
            ("structured_data", self._structured_data_step),
            ("corpus_summary", self._corpus_summary_step),
            ("web_search", self._web_step),
            ("temporal_reasoning", self._temporal_step),
            ("evidence_selection", self.evidence_selection_agent.run),
            ("conflict_resolution", self._conflict_step),
            ("math_reasoning", self._math_step),
            ("visualization", self._visualization_step),
            ("synthesis_agent", self.synthesis_agent.synthesize),
            ("output_guard", self._output_guard_step),
            ("reflection_node", self._reflection_step),
        ]
        for name, fn in nodes:
            builder.add_node(name, _with_run(fn))

        builder.set_entry_point("input_guard")
        builder.add_conditional_edges("input_guard", self._route_scope, {"proceed": "understanding", "reject": "rejection_node"})
        builder.add_conditional_edges("understanding", self._route_scope, {"proceed": "supervisor", "reject": "rejection_node"})
        builder.add_edge("rejection_node", END)
        chain = ["supervisor", "hybrid_retrieval", "document_intelligence", "graph_retrieval", "vision_retrieval",
                 "structured_data", "corpus_summary", "web_search", "temporal_reasoning", "evidence_selection", "conflict_resolution",
                 "math_reasoning", "visualization", "synthesis_agent", "output_guard"]
        for a, b in zip(chain, chain[1:]):
            builder.add_edge(a, b)
        builder.add_conditional_edges("output_guard", self._route_after_output_guard,
                                      {"accept": END, "reflect": "reflection_node"})
        # Reflection re-writes the answer with the verifier's feedback (retrieval is not repeated).
        builder.add_edge("reflection_node", "synthesis_agent")
        return builder.compile()

    # ------------------------------------------------------------------ front
    def _input_guard_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        started = time.perf_counter()
        question, _ = split_language_instruction(state.get("user_query", ""))
        problem = self.input_guard.screen(question)
        if not problem:
            return {"agent_traces": [trace("input_guard", "completed", "Question accepted.", started)]}
        from core.state import IntentClassificationResult
        result = IntentClassificationResult(primary_intent="rejected", is_in_scope=False, rejection_reason=problem, confidence=1.0)
        return {"intent_result": result, "agent_traces": [trace("input_guard", "rejected", problem, started)]}

    def _route_scope(self, state: AgentWorkflowState) -> Literal["proceed", "reject"]:
        intent_res = state.get("intent_result")
        return "reject" if intent_res is not None and not intent_res.is_in_scope else "proceed"

    def _understanding_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        One model call at most: the understanding agent reads the question (rules for simple
        ones), then context memory, language, semantic structure, intent, entity resolution
        against the graph and query expansion are derived from it without further calls.
        """
        started = time.perf_counter()
        question, requested_language = split_language_instruction(state.get("user_query", ""))
        history = state.get("conversation_history") or []
        u = self.understanding_agent.understand(question, history, is_corpus_question(question))

        memory = self.context_memory_agent.remember(state.get("memory_state"), question, u)
        langs = self.multilingual_agent.languages(question, u, requested_language)
        u["language"] = langs["question"]
        semantic_q = self.semantic_nlu.from_understanding(question, u)
        intent_res = self.intent_classifier.from_understanding(semantic_q, u)
        doc_ids = [d for d in (state.get("document_ids") or []) if d]
        resolved = self.entity_resolution_agent.resolve_against_graph(semantic_q.entities, doc_ids or None)
        canonical = [r["canonical_name"] for r in resolved if r["matched"] != "none" and r["canonical_name"] != r["mention"]]
        variants = self.query_expansion_agent.variants_from(u, semantic_q.resolved_query, canonical)
        semantic_q = semantic_q.model_copy(update={
            "entities": list(dict.fromkeys(semantic_q.entities + canonical))[:12],
            "constraints": {**semantic_q.constraints, "retrieval_variants": variants},
        })
        legacy = QueryIntentContract(
            raw_query=question, refined_query=semantic_q.resolved_query,
            intent=QueryIntentType.OUT_OF_SCOPE if not intent_res.is_in_scope else (
                QueryIntentType.COMPARATIVE_AUDIT if u["intent"] == "comparison" else
                QueryIntentType.DEEP_SUMMARY if u["intent"] == "summary" else
                QueryIntentType.MULTI_HOP_RELATIONAL if u["intent"] == "relationship" else
                QueryIntentType.VISUAL_DIAGRAM if u["needs"].get("figures") else QueryIntentType.FACTUAL_LOOKUP),
            is_in_scope=intent_res.is_in_scope, rejection_reason=intent_res.rejection_reason,
            confidence=intent_res.confidence, entities_mentioned=semantic_q.entities, sub_questions=semantic_q.sub_questions,
            requires_graph=bool(u["needs"].get("graph")), requires_vision=bool(u["needs"].get("figures")),
        )
        needed = [n.replace("_", " ") for n, v in (u["needs"] or {}).items() if v]
        detail = ("1 model call" if u.get("used_model") else "no model call") + f" ({u.get('why')}); {u['intent']}"
        if needed:
            detail += "; needs " + ", ".join(needed)
        if langs["question"] != "en" or langs["answer"] != "en":
            detail += f"; {langs['question']} -> answer in {langs['answer_name']}"
        out: Dict[str, Any] = {
            "user_query": semantic_q.resolved_query,
            "semantic_query": semantic_q,
            "intent_result": intent_res,
            "intent": legacy,
            "memory_state": memory,
            "needs": {**u["needs"], "web_mode": (state.get("needs") or {}).get("web_mode", "auto")},
            "answer_language": langs["answer"],
            "time_filter": u.get("time_range"),
            "agent_traces": [trace("understanding", "completed", detail, started,
                                   search_queries=[semantic_q.resolved_query] + variants)],
        }
        if resolved:
            out["graph_context"] = [{"source": "entity_resolution", "resolved_entities": resolved, "nodes": [], "edges": []}]
        return out

    def _rejection_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        intent_res = state.get("intent_result")
        reason = intent_res.rejection_reason if intent_res else "The request is outside what OmniDoc can answer."
        response = f"**OmniDoc could not process this request.**\n\n{reason}"
        return {"verified_response": response, "draft_response": response, "is_complete": True}

    def _supervisor_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Builds the execution plan from the question's needs (no model call) and logs it."""
        started = time.perf_counter()
        plan: QueryExecutionPlan = self.query_planner.plan_from_needs(state.get("semantic_query"), state.get("needs") or {})
        out = self.supervisor.plan_and_route({**state, "execution_plan": plan})
        used = self.execution_guard.usage(state.get("run_id") or "")
        out.update({
            "execution_plan": plan,
            "agent_traces": (out.get("agent_traces") or []) + [trace(
                "supervisor", "completed",
                f"{_plural(len(plan.steps), 'step')}; budget {self.execution_guard.max_llm_calls} model calls "
                f"({used['calls']} used)", started)],
        })
        return out

    # -------------------------------------------------------------- retrieval
    def _needs(self, state: AgentWorkflowState) -> Dict[str, Any]:
        return state.get("needs") or {}

    def _allow(self, state: AgentWorkflowState, step: str, calls: int = 1) -> bool:
        return self.execution_guard.allow(state.get("run_id") or "", step, calls)

    def _document_intelligence_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        return self.document_intelligence_agent.run(state)

    def _graph_retrieval_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        semantic_q = state.get("semantic_query")
        if self.graph_agent and (self._needs(state).get("graph") or (semantic_q and semantic_q.entities)):
            return self.graph_agent.run(state)
        return {}

    def _vision_retrieval_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Reads figures when the question is about one, or when the best passages sit on pages
        that are mostly pictures or charts (slides, brochures, infographics), whose content the
        text layer misses.
        """
        if not self.vision_agent:
            return {}
        wanted = self._needs(state).get("figures") or self.vision_agent.visual_pages(state)
        if wanted and self._allow(state, "vision", 2):
            return self.vision_agent.run(state)
        return {}

    def _structured_data_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """SQL over document tables and library records, when any matches the question."""
        if self.structured_data_agent is None:
            return {}
        needs = self._needs(state)
        query = state.get("user_query", "")
        if needs.get("whole_documents") and not (needs.get("library") or asks_about_tables(query)):
            return {}  # questions about whole documents are answered from summaries
        if not self.structured_data_agent.has_data(state.get("document_ids") or None, needs):
            return {}
        return self.structured_data_agent.run(state)

    def _corpus_summary_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Document and section summaries for questions about whole documents or the collection."""
        if self.corpus_agent is None or not self._needs(state).get("whole_documents"):
            return {}
        return self.corpus_agent.run(state)

    def _web_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        if self.web_search_agent is None:
            return {}
        return self.web_search_agent.run(state)

    def _temporal_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        return self.temporal_agent.run(state)

    # ------------------------------------------------------------- analysis
    def _conflict_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        if not self._allow(state, "conflict audit"):
            return {}
        return self.conflict_resolution_agent.run(state)

    def _math_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        if self._needs(state).get("calculation") and self._allow(state, "calculation"):
            return self.math_agent.run(state)
        return {}

    def _visualization_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        if self._needs(state).get("chart") and self._allow(state, "chart"):
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
            evidence_package=state.get("evidence_package"),
            sources=state.get("sources") or None,
            visual_context=state.get("visual_context", []),
            web_context=state.get("web_context", []),
            table_results=state.get("table_results", []),
            summary_context=state.get("summary_context", []),
        )
        # Wrong citation numbers are fixed in place by the sentence checker.
        verified_resp = verification.corrected_answer or state.get("draft_response", "")
        out: Dict[str, Any] = {"verification": verification, "verified_response": verified_resp}
        if verification.action == "accept":
            out["is_complete"] = True
        return out

    def _route_after_output_guard(self, state: AgentWorkflowState) -> Literal["accept", "reflect"]:
        """
        One rewrite at most, and only when it is worth two more model calls: a sentence
        contradicts its sources, or less than 60% of the answer is supported. Single weak
        sentences stay and are underlined for the reader instead.
        """
        verification = state.get("verification")
        if not verification or verification.action == "accept":
            return "accept"
        if state.get("reflection_count", 0) >= state.get("max_iterations", 1):
            return "accept"
        contradicted = any(s.get("verdict") == "contradicted" for s in verification.sentences or [])
        weak = (verification.faithfulness_score or 0.0) < 0.6
        if not (contradicted or weak) or not self._allow(state, "revision", 2):
            return "accept"
        return "reflect"

    def _reflection_step(self, state: AgentWorkflowState) -> Dict[str, Any]:
        verification = state.get("verification")
        feedback = verification.feedback if verification and verification.feedback else "Some claims were not supported by the cited evidence."
        unsupported = list(getattr(verification, "unsupported_claims", []) or [])
        if unsupported:
            feedback = feedback + " Unsupported claims: " + "; ".join(unsupported[:6])
        count = state.get("reflection_count", 0) + 1
        logger.info(f"Reflection {count}: {feedback}")
        return {
            "reflection_count": count,
            "reflection_feedback": feedback,
            "errors": [f"Reflection triggered: {feedback}"]
        }

    def _initial_state(
        self,
        user_query: str,
        document_ids: Optional[list] = None,
        session_id: str = "default_session",
        conversation_history: Optional[list] = None,
        run_id: Optional[str] = None,
        web_mode: str = "auto",
    ) -> AgentWorkflowState:
        return {
            "session_id": session_id,
            "run_id": run_id or f"run_{uuid.uuid4().hex[:12]}",
            "user_query": user_query,
            "document_ids": document_ids or [],
            "needs": {"web_mode": web_mode if web_mode in ("auto", "on", "off") else "auto"},
            "answer_language": "en",
            "time_filter": None,
            "timeline": [],
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
            "table_results": [],
            "summary_context": [],
            "evidence_package": None,
            "conflicts": [],
            "draft_response": "",
            "verified_response": "",
            "sources": [],
            "verification": None,
            "iteration_count": 0,
            "max_iterations": 1,
            "reflection_count": 0,
            "reflection_feedback": None,
            "errors": [],
            "agent_traces": [],
            "conversation_history": conversation_history or [],
            "is_complete": False
        }

    def execute(
        self,
        user_query: str,
        document_ids: list = None,
        session_id: str = "default_session",
        conversation_history: list = None
    ) -> Dict[str, Any]:
        """Executes the compiled LangGraph workflow end-to-end."""
        initial_state = self._initial_state(user_query, document_ids, session_id, conversation_history)
        run_id = initial_state["run_id"]
        self.execution_guard.start(run_id)
        try:
            final = self.graph.invoke(initial_state, config={"recursion_limit": 50})
        finally:
            usage = self.execution_guard.finish(run_id)
        final["usage"] = usage
        return final

    def execute_stream(
        self,
        user_query: str,
        document_ids: list = None,
        session_id: str = "default_session",
        conversation_history: list = None,
        web_mode: str = "auto",
    ) -> Iterator[Tuple[str, Dict[str, Any]]]:
        """
        Runs the workflow in a worker thread and yields events as they happen:
        ("step", {node, label, detail, duration_ms, skipped}) after every node, ("sources", [...])
        before the answer is written, ("delta", text) while it is written, ("reset", [...]) when a
        draft is replaced, and finally ("result", final_state) with "usage" (model calls, tokens).
        """
        initial_state = self._initial_state(user_query, document_ids, session_id, conversation_history, web_mode=web_mode)
        run_id = initial_state["run_id"]
        events: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        streaming.open_channel(run_id, lambda event, data: events.put((event, data)))
        self.execution_guard.start(run_id)

        def work() -> None:
            final_state: Dict[str, Any] = dict(initial_state)
            last = time.perf_counter()
            try:
                for mode, chunk in self.graph.stream(initial_state, config={"recursion_limit": 50},
                                                     stream_mode=["updates", "values"]):
                    if mode == "values":
                        final_state = chunk
                        continue
                    now = time.perf_counter()
                    for node, update in (chunk or {}).items():
                        events.put(("step", {
                            "node": node,
                            "label": NODE_LABELS.get(node, node.replace("_", " ").capitalize()),
                            "detail": describe_step(node, update),
                            "duration_ms": int((now - last) * 1000),
                            "skipped": not update,
                        }))
                    last = now
                events.put(("_final", final_state))
            except Exception as e:  # surfaced to the caller below
                events.put(("_error", e))

        worker = threading.Thread(target=work, name=f"workflow-{run_id}", daemon=True)
        worker.start()
        try:
            while True:
                event, data = events.get()
                if event == "_error":
                    raise data
                if event == "_final":
                    data["usage"] = self.execution_guard.usage(run_id)
                    yield "result", data
                    break
                yield event, data
        finally:
            streaming.close_channel(run_id)
            self.execution_guard.finish(run_id)
