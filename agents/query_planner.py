"""
Query Decomposition and Dynamic Execution Planner for OmniDoc.
Transforms rich SemanticQuery representations and Multi-Label Intents
into an executable machine-readable DAG of PlanSteps with dependencies.
"""
import re
import json
import logging
from typing import Dict, Any, List
import ollama

from core.state import SemanticQuery, IntentClassificationResult, QueryExecutionPlan, PlanStep

logger = logging.getLogger("OmniDoc.QueryPlanner")

PLANNER_SYSTEM_PROMPT = """You are the Dynamic Query Planner of OmniDoc.
Your mission is to decompose the user's SemanticQuery into an optimized, executable Directed Acyclic Graph (DAG) of PlanSteps.

Available Specialized Agents:
- "entity_resolution_agent": Disambiguates named entities and maps them to canonical IDs.
- "temporal_reasoning_agent": Analyzes time ranges, intervals, and historical sequence.
- "query_expansion_agent": Generates dense, sparse, and graph query variants.
- "advanced_hybrid_retrieval": Performs dense vector + BM25 search on LanceDB.
- "knowledge_graph_agent": Queries Kùzu for entity relationships, paths, and subgraphs.
- "document_intelligence_agent": Navigates table structures, layouts, and AST metadata.
- "vision_agent": Directly inspects charts, plots, schematics, and diagrams.
- "math_agent": Executes sandboxed Python/SymPy/NumPy computations (percentages, CAGR, stats).
- "visualization_agent": Generates interactive Plotly/Altair charts from structured data.
- "evidence_selection_agent": Ranks, deduplicates, and compresses candidate evidence.
- "evidence_verification_agent": Audits evidence sufficiency and resolves source conflicts.
- "synthesis_agent": Synthesizes final response strictly citing verified evidence.
- "output_groundedness_agent": Impartial NLI check verifying claims against evidence.

Rules:
1. Do NOT over-agentify simple queries! For a simple fact, use ONLY: [advanced_hybrid_retrieval, synthesis_agent, output_groundedness_agent].
2. For comparative or numerical questions, sequence: retrieval -> evidence_selection -> math_agent -> [optional: visualization_agent] -> synthesis_agent -> output_groundedness_agent.
3. Every step MUST have an "id", "agent", "description", and "depends_on" list of step IDs.
4. Output ONLY valid JSON matching this schema:
{{
    "goal": "...",
    "execution_mode": "dag" | "single_agent" | "linear_pipeline",
    "estimated_complexity": "low" | "medium" | "high",
    "steps": [
        {{
            "id": "step_1_...",
            "agent": "...",
            "description": "...",
            "depends_on": [],
            "inputs": {{}},
            "fallback_agent": null or "..."
        }}
    ]
}}
"""


class QueryPlanner:
    """Decomposes complex requests into machine-readable execution graphs."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def generate_plan(
        self,
        semantic_query: SemanticQuery,
        intent_result: IntentClassificationResult
    ) -> QueryExecutionPlan:
        """
        Creates a dynamic DAG plan tailored to the semantic requirements.
        """
        # Fast path: Simple factual lookup with no math/viz/temporal needs
        operations = set(semantic_query.operations)
        is_simple = (
            intent_result.primary_intent in ["factual_retrieval", "semantic_search"]
            and not semantic_query.temporal_constraints
            and not any(op in operations for op in ["calculate", "compare", "visualize"])
            and not semantic_query.ambiguity_detected
        )

        if is_simple:
            logger.info("QueryPlanner: Constructing streamlined single-path plan.")
            return QueryExecutionPlan(
                goal=semantic_query.goal,
                execution_mode="linear_pipeline",
                estimated_complexity="low",
                steps=[
                    PlanStep(
                        id="step_1_retrieval",
                        agent="advanced_hybrid_retrieval",
                        description="Retrieve relevant passages from document chunks",
                        depends_on=[]
                    ),
                    PlanStep(
                        id="step_2_synthesis",
                        agent="synthesis_agent",
                        description="Synthesize grounded answer with inline citations",
                        depends_on=["step_1_retrieval"]
                    ),
                    PlanStep(
                        id="step_3_groundedness",
                        agent="output_groundedness_agent",
                        description="Verify output groundedness against evidence",
                        depends_on=["step_2_synthesis"]
                    )
                ]
            )

        # Complex path: Dynamic DAG generation via Planner LLM
        prompt = f"""{PLANNER_SYSTEM_PROMPT}

SEMANTIC QUERY:
{json.dumps(semantic_query.model_dump(), indent=2)}

INTENT RESULT:
{json.dumps(intent_result.model_dump(), indent=2)}
"""
        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "num_predict": 1024},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            steps = [PlanStep(**s) for s in parsed.get("steps", [])]

            return QueryExecutionPlan(
                goal=parsed.get("goal", semantic_query.goal),
                execution_mode=parsed.get("execution_mode", "dag"),
                estimated_complexity=parsed.get("estimated_complexity", "medium"),
                steps=steps
            )

        except Exception as e:
            logger.warning(f"Planner LLM failed ({e}). Generating robust default DAG.")
            return self._build_robust_default_dag(semantic_query, intent_result)

    def _build_robust_default_dag(
        self,
        semantic_query: SemanticQuery,
        intent_result: IntentClassificationResult
    ) -> QueryExecutionPlan:
        """Deterministic DAG builder covering multi-agent requirements."""
        steps = []
        retrieval_deps = []

        # 1. Entity Resolution if entities exist
        if semantic_query.entities:
            steps.append(PlanStep(
                id="step_1_entity_res",
                agent="entity_resolution_agent",
                description="Resolve and link query entities",
                depends_on=[]
            ))
            retrieval_deps.append("step_1_entity_res")

        # 2. Parallel Retrieval (Hybrid + KG)
        steps.append(PlanStep(
            id="step_2_hybrid_retrieval",
            agent="advanced_hybrid_retrieval",
            description="Dense + BM25 hybrid search",
            depends_on=retrieval_deps
        ))
        steps.append(PlanStep(
            id="step_2_kg_retrieval",
            agent="knowledge_graph_agent",
            description="Traverse Kùzu property graph",
            depends_on=retrieval_deps
        ))

        last_dep = ["step_2_hybrid_retrieval", "step_2_kg_retrieval"]

        # 3. Vision if visual modality requested
        if "visual" in semantic_query.modality_requirements or "multimodal_analysis" in intent_result.secondary_intents:
            steps.append(PlanStep(
                id="step_3_vision",
                agent="vision_agent",
                description="Inspect diagrams and figures",
                depends_on=retrieval_deps
            ))
            last_dep.append("step_3_vision")

        # 4. Evidence Selection
        steps.append(PlanStep(
            id="step_4_evidence_selection",
            agent="evidence_selection_agent",
            description="Rerank and compress candidate evidence",
            depends_on=last_dep
        ))
        last_dep = ["step_4_evidence_selection"]

        # 5. Math computation if required
        if "calculate" in semantic_query.operations or "numerical_calculation" in intent_result.secondary_intents:
            steps.append(PlanStep(
                id="step_5_math",
                agent="math_agent",
                description="Compute metrics and statistics in sandboxed Python",
                depends_on=last_dep
            ))
            last_dep = ["step_5_math"]

        # 6. Visualization if requested
        if "visualize" in semantic_query.operations or "chart" in semantic_query.output_requirements:
            steps.append(PlanStep(
                id="step_6_viz",
                agent="visualization_agent",
                description="Generate interactive Plotly visualization",
                depends_on=last_dep
            ))
            last_dep.append("step_6_viz")

        # 7. Synthesis & Groundedness
        steps.append(PlanStep(
            id="step_7_synthesis",
            agent="synthesis_agent",
            description="Synthesize verified multi-source answer with citations",
            depends_on=last_dep
        ))
        steps.append(PlanStep(
            id="step_8_groundedness",
            agent="output_groundedness_agent",
            description="Evaluate faithfulness and groundedness score",
            depends_on=["step_7_synthesis"]
        ))

        return QueryExecutionPlan(
            goal=semantic_query.goal,
            execution_mode="dag",
            estimated_complexity="medium",
            steps=steps
        )
