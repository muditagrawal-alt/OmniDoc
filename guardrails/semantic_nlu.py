"""
Semantic NLU & Query Understanding Layer for OmniDoc.
Zero-keyword natural language understanding using structured in-context learning.
Deconstructs queries into goals, entities, constraints, operations, and ambiguity.
"""
import re
import json
import logging
from typing import Optional, Dict, Any, List
import ollama

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

Exemplar 1:
Query: "Compare the revenue growth of Microsoft and Google from 2020 to 2024, explain the major reasons for the differences, and show me a chart."
Output:
{
  "goal": "comparative financial growth analysis and visualization",
  "task_types": ["comparison", "mathematical_analysis", "visualization", "temporal_reasoning"],
  "entities": ["Microsoft", "Google"],
  "entity_types": {"Microsoft": "Organization", "Google": "Organization"},
  "relationships": ["competitive comparison"],
  "attributes": ["revenue", "revenue_growth"],
  "constraints": {},
  "temporal_constraints": {"start_year": 2020, "end_year": 2024, "interval": "annual"},
  "numerical_constraints": {"metrics": ["growth_rate", "percentage_change"]},
  "geographic_constraints": null,
  "operations": ["retrieve", "calculate", "compare", "visualize", "explain"],
  "output_requirements": ["narrative", "chart", "citations"],
  "modality_requirements": ["text", "tabular", "visual"],
  "language": "en",
  "ambiguity_detected": false,
  "ambiguity_details": null,
  "sub_questions": [
    "What was Microsoft's revenue each year from 2020 to 2024?",
    "What was Google's revenue each year from 2020 to 2024?",
    "What was the year-over-year revenue growth rate for both companies?",
    "What were the primary drivers and business factors behind the difference in growth?"
  ]
}

Exemplar 2:
Query: "Who was CEO of Microsoft in 2012, and who succeeded them?"
Output:
{
  "goal": "historical leadership query with succession sequence",
  "task_types": ["temporal_reasoning", "multi_hop_relational", "factual_lookup"],
  "entities": ["Microsoft"],
  "entity_types": {"Microsoft": "Organization"},
  "relationships": ["leadership", "succession"],
  "attributes": ["CEO", "successor"],
  "constraints": {},
  "temporal_constraints": {"target_year": 2012, "sequence": "successor_after"},
  "numerical_constraints": null,
  "geographic_constraints": null,
  "operations": ["retrieve", "explain"],
  "output_requirements": ["narrative", "citations"],
  "modality_requirements": ["text"],
  "language": "en",
  "ambiguity_detected": false,
  "ambiguity_details": null,
  "sub_questions": [
    "Who was the CEO of Microsoft as of 2012?",
    "When did their tenure end and who was appointed as the successor?"
  ]
}
"""


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
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": full_prompt}],
                options={"temperature": 0.0, "num_predict": 1024},
                stream=False
            )
            raw_text = response["message"]["content"].strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                raw_text = re.sub(r"\s*```$", "", raw_text)

            parsed = json.loads(raw_text)

            return SemanticQuery(
                raw_query=raw_query,
                resolved_query=effective_query,
                goal=parsed.get("goal") or "Information retrieval",
                task_types=parsed.get("task_types") or ["factual_lookup"],
                entities=parsed.get("entities") or [],
                entity_types=parsed.get("entity_types") or {},
                relationships=parsed.get("relationships") or [],
                attributes=parsed.get("attributes") or [],
                constraints=parsed.get("constraints") or {},
                temporal_constraints=parsed.get("temporal_constraints"),
                numerical_constraints=parsed.get("numerical_constraints"),
                geographic_constraints=parsed.get("geographic_constraints"),
                operations=parsed.get("operations") or ["retrieve"],
                output_requirements=parsed.get("output_requirements") or ["narrative", "citations"],
                modality_requirements=parsed.get("modality_requirements") or ["text"],
                language=parsed.get("language") or "en",
                ambiguity_detected=bool(parsed.get("ambiguity_detected", False)),
                ambiguity_details=parsed.get("ambiguity_details"),
                sub_questions=parsed.get("sub_questions") or [effective_query]
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

    # Convenience alias
    analyze = understand_query


# Backward-compatible and convenience alias
SemanticNLU = SemanticNLUEngine
