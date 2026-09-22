"""
Supervisor / Orchestrator Agent Node for LangGraph.
Monitors DAG plan execution, tracks agent execution traces, evaluates state transitions,
and manages self-correction budgets across multi-agent turns.
"""
import logging
import time
from typing import Dict, Any, List, Optional
from core.state import AgentWorkflowState, QueryExecutionPlan

logger = logging.getLogger("OmniDoc.Supervisor")


class SupervisorAgent:
    """Coordinates agent execution, tracks progress against DAG steps, and enforces budget guards."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def plan_and_route(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Coordinates execution trace and iteration tracking for the active DAG.
        """
        current_iter = state.get("iteration_count", 0)
        exec_plan: Optional[QueryExecutionPlan] = state.get("execution_plan")
        
        # Build readable plan string for UI / logs
        if exec_plan and exec_plan.steps:
            plan_descriptions = [f"{s.agent}: {s.description}" for s in exec_plan.steps]
        else:
            plan_descriptions = ["retrieve_document_chunks", "query_knowledge_graph", "synthesize_and_verify"]

        logger.info(f"Supervisor active (Iteration {current_iter + 1}) - Plan steps: {len(plan_descriptions)}")

        trace_entry = {
            "timestamp": time.time(),
            "iteration": current_iter + 1,
            "status": "in_progress",
            "active_plan": plan_descriptions
        }

        return {
            "plan": plan_descriptions,
            "iteration_count": current_iter + 1,
            "agent_traces": [trace_entry]
        }

