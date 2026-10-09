"""
Semantic NLU & Query Understanding Layer for OmniDoc.
Zero-keyword natural language understanding using structured in-context learning.
Deconstructs queries into goals, entities, constraints, operations, and ambiguity.
"""
import re
import logging
from typing import Optional, Dict, Any, List

from core.state import SemanticQuery, ConversationMemoryState

logger = logging.getLogger("OmniDoc.SemanticNLU")

SEMANTIC_NLU_SYSTEM_PROMPT = """You are the Semantic NLU and Natural Language Understanding Engine of OmniDoc.
Your responsibility is to deeply analyze the user query in the context of recent conversational memory.
Deconstruct the query into an exact, highly structured semantic representation.

DO NOT use keyword matching. Use deep contextual semantics.

You must extract:
1. "goal": The overarching analytical, comparative, or factual objective.
2. "task_types": List from [factual_lookup, comparison, mathematical_analysis, statistical_reasoning, visualization, temporal_reasoning, document_intelligence, table_analysis, multi_hop_relational, summarization, exploratory_research, structured_data_query, out_of_scope].
3. "entities": Specific named entities, organizations, systems, concepts, or components mentioned.
4. "entity_types": Object mapping each entity to its category (e.g. Organization, Metric, Technology, Regulation, Component).
5. "relationships": Explicit relationships to investigate (e.g. "acquired by", "revenue of", "depends on", "impact on").
6. "attributes": Specific attributes or variables requested (e.g. "operating margin", "growth rate", "CEO", "architecture").
7. "constraints": General domain bounds.
8. "temporal_constraints": Object with keys like "start_year", "end_year", "interval", "relative_order" (e.g. "before", "after", "between") if applicable, else null.
9. "numerical_constraints": Numerical bounds, formulas, or math operations required if applicable, else null.
10. "geographic_constraints": Locations, regions, countries mentioned if applicable, else null.
11. "operations": List from ["retrieve", "calculate", "compare", "visualize", "explain", "summarize", "extract"].
12. "output_requirements": List from ["narrative", "table", "chart", "latex_formula", "citations", "code"].
13. "modality_requirements": List from ["text", "tabular", "visual", "spatial"].
14. "language": Language code (e.g. "en", "hi", "fr", "es").
15. "ambiguity_detected": Boolean true if key terms or pronouns cannot be resolved from query/context.
16. "ambiguity_details": Explanation of ambiguity if detected, else null.
17. "sub_questions": Discrete questions that decompose the multi-part request.

Respond with ONLY valid JSON matching this schema.
Only include "calculate" in operations when arithmetic is required, and only include "visualize" / "chart" when the user explicitly asks for a chart, plot, graph or visual.
Extract only entities that literally appear in the query; never add names, numbers or years that are not in it.

Exemplar 1:
Query: "Compare the error rates of the baseline model and the proposed model in Table 3, compute the relative improvement, and plot both."
Output:
{
  "goal": "comparative evaluation of two models with a computed improvement and a chart",
  "task_types": ["comparison", "mathematical_analysis", "visualization", "table_analysis"],
  "entities": ["baseline model", "proposed model", "Table 3"],
  "entity_types": {"baseline model": "Method", "proposed model": "Method", "Table 3": "Table"},
  "relationships": ["performance comparison"],
  "attributes": ["error rate", "relative improvement"],
  "constraints": {},
  "temporal_constraints": null,
  "numerical_constraints": {"metrics": ["relative_change"]},
  "geographic_constraints": null,
  "operations": ["retrieve", "compare", "calculate", "visualize"],
  "output_requirements": ["narrative", "chart", "citations"],
  "modality_requirements": ["text", "tabular", "visual"],
  "language": "en",
  "ambiguity_detected": false,
  "ambiguity_details": null,
  "sub_questions": [
    "What is the error rate of the baseline model in Table 3?",
    "What is the error rate of the proposed model in Table 3?"
  ]
}

Exemplar 2:
Query: "Who approved the policy described in section 4, and when did it take effect?"
Output:
{
  "goal": "identify the approving party and effective date of a policy",
  "task_types": ["factual_lookup", "temporal_reasoning"],
  "entities": ["section 4"],
  "entity_types": {"section 4": "Section"},
  "relationships": ["approved by"],
  "attributes": ["approver", "effective date"],
  "constraints": {},
  "temporal_constraints": {"sequence": "effective_date"},
  "numerical_constraints": null,
  "geographic_constraints": null,
  "operations": ["retrieve", "explain"],
  "output_requirements": ["narrative", "citations"],
  "modality_requirements": ["text"],
  "language": "en",
  "ambiguity_detected": false,
  "ambiguity_details": null,
  "sub_questions": [
    "Who approved the policy described in section 4?",
    "When did the policy in section 4 take effect?"
  ]
}
"""


def _str_list(v: Any) -> List[str]:
    """Coerces LLM output into a list of non-empty strings."""
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return [str(x).strip() for x in v if isinstance(x, (str, int, float)) and not isinstance(x, bool) and str(x).strip()]


def _str_dict(v: Any) -> Dict[str, str]:
    if not isinstance(v, dict):
        return {}
    return {str(k): str(val) for k, val in v.items() if isinstance(val, (str, int, float))}


def _opt_dict(v: Any) -> Optional[Dict[str, Any]]:
    if isinstance(v, dict) and v:
        return v
    if isinstance(v, list) and v:
        return {"values": v}
    if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none"):
        return {"description": v.strip()}
    return None


class SemanticNLUEngine:
    """Parses natural language queries into rich semantic representations."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def understand_query(
        self,
        raw_query: str,
        resolved_query: Optional[str] = None,
        memory_state: Optional[ConversationMemoryState] = None
    ) -> SemanticQuery:
        """
        Executes few-shot semantic NLU extraction on the query.
        """
        effective_query = resolved_query or raw_query
        
        context_prompt = ""
        if memory_state and (memory_state.active_entities or memory_state.active_topic):
            context_prompt = f"\nACTIVE CONVERSATION STATE:\n- Active Entities: {memory_state.active_entities}\n- Active Topic: {memory_state.active_topic}\n- Active Time Range: {memory_state.active_time_range}\n"

        full_prompt = f"{SEMANTIC_NLU_SYSTEM_PROMPT}\n{context_prompt}\nUSER QUERY:\n{effective_query}"

        try:
            from agents.llm_utils import chat_json  # local import keeps guardrails importable standalone
            parsed = chat_json(self.model_name, full_prompt, num_predict=900)
            if not isinstance(parsed, dict):
                raise ValueError("expected a JSON object")

            sub_questions = _str_list(parsed.get("sub_questions"))[:6] or [effective_query]
            return SemanticQuery(
                raw_query=raw_query,
                resolved_query=effective_query,
                goal=str(parsed.get("goal") or "Information retrieval")[:300],
                task_types=_str_list(parsed.get("task_types")) or ["factual_lookup"],
                entities=[e for e in _str_list(parsed.get("entities")) if len(e) <= 120][:10],
                entity_types=_str_dict(parsed.get("entity_types")),
                relationships=_str_list(parsed.get("relationships")),
                attributes=_str_list(parsed.get("attributes")),
                constraints=parsed.get("constraints") if isinstance(parsed.get("constraints"), dict) else {},
                temporal_constraints=_opt_dict(parsed.get("temporal_constraints")),
                numerical_constraints=_opt_dict(parsed.get("numerical_constraints")),
                geographic_constraints=_opt_dict(parsed.get("geographic_constraints")),
                operations=[o.lower() for o in _str_list(parsed.get("operations"))] or ["retrieve"],
                output_requirements=[o.lower() for o in _str_list(parsed.get("output_requirements"))] or ["narrative", "citations"],
                modality_requirements=[o.lower() for o in _str_list(parsed.get("modality_requirements"))] or ["text"],
                language=str(parsed.get("language") or "en")[:10],
                ambiguity_detected=parsed.get("ambiguity_detected") is True,
                ambiguity_details=parsed.get("ambiguity_details") if isinstance(parsed.get("ambiguity_details"), str) else None,
                sub_questions=sub_questions
            )

        except Exception as e:
            logger.warning(f"Semantic NLU extraction fallback triggered ({e}).")
            return self._heuristic_fallback(raw_query, effective_query)

    def _heuristic_fallback(self, raw_query: str, effective_query: str) -> SemanticQuery:
        """Deterministic semantic fallback when LLM is offline."""
        words = [w for w in effective_query.split() if len(w) > 4 and w.isalnum()]
        return SemanticQuery(
            raw_query=raw_query,
            resolved_query=effective_query,
            goal="Analyze and retrieve document evidence",
            task_types=["factual_lookup"],
            entities=words[:3],
            entity_types={w: "Concept" for w in words[:3]},
            relationships=[],
            attributes=[],
            constraints={},
            temporal_constraints=None,
            numerical_constraints=None,
            geographic_constraints=None,
            operations=["retrieve", "explain"],
            output_requirements=["narrative", "citations"],
            modality_requirements=["text"],
            language="en",
            ambiguity_detected=False,
            ambiguity_details=None,
            sub_questions=[effective_query]
        )

    @staticmethod
    def from_understanding(raw_query: str, u: Dict[str, Any]) -> SemanticQuery:
        """The structured query representation, from the understanding step (no model call)."""
        needs = u.get("needs") or {}
        intent = u.get("intent") or "factual"
        operations = ["retrieve"]
        if needs.get("calculation"):
            operations.append("calculate")
        if intent == "comparison":
            operations.append("compare")
        if needs.get("chart"):
            operations.append("visualize")
        if intent == "summary" or needs.get("whole_documents"):
            operations.append("summarize")
        modality = ["text"] + (["visual"] if needs.get("figures") else []) + (["tabular"] if needs.get("tables") else [])
        task_map = {"factual": "factual_lookup", "comparison": "comparison", "summary": "summarization",
                    "calculation": "mathematical_analysis", "timeline": "temporal_reasoning", "table": "table_analysis",
                    "relationship": "multi_hop_relational", "exploration": "exploratory_research", "library": "structured_data_query"}
        tr = u.get("time_range") or None
        entities = _str_list(u.get("entities"))[:12]
        return SemanticQuery(
            raw_query=raw_query,
            resolved_query=u.get("resolved_query") or raw_query,
            goal=(u.get("sub_questions") or [raw_query])[0][:300],
            task_types=[task_map.get(intent, "factual_lookup")] + (["temporal_reasoning"] if needs.get("timeline") and intent != "timeline" else []),
            entities=entities,
            entity_types={e: "Concept" for e in entities},
            constraints={"retrieval_variants": _str_list(u.get("search_queries"))[1:4]},
            temporal_constraints={"start": tr.get("start"), "end": tr.get("end")} if tr else None,
            operations=operations,
            output_requirements=["narrative", "citations"] + (["chart"] if needs.get("chart") else []),
            modality_requirements=modality,
            language=u.get("language") or "en",
            sub_questions=_str_list(u.get("sub_questions"))[:6] or [raw_query],
        )

    # Convenience alias
    analyze = understand_query


# Backward-compatible and convenience alias
SemanticNLU = SemanticNLUEngine
