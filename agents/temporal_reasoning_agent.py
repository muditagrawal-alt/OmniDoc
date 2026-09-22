"""
Temporal Reasoning Agent for OmniDoc.
Evaluates time intervals, sequence relationships (before, after, during, since),
and enforces historical validity on entities and claims.
"""
import re
import json
import logging
from typing import Dict, Any, List
import ollama

from core.state import AgentWorkflowState, SemanticQuery

logger = logging.getLogger("OmniDoc.TemporalReasoning")

TEMPORAL_PROMPT = """You are the Temporal Reasoning Specialist of OmniDoc.
Analyze the query's temporal constraints and the retrieved context to verify that facts, metrics, or relationships match the required time frame.

TEMPORAL CONSTRAINTS:
{temporal_constraints}

QUERY:
{query}

CONTEXT:
{context}

Output schema (JSON):
{{
    "time_frame_valid": true | false,
    "target_period": "e.g. 2020-2024 or 2012",
    "chronological_sequence": ["Event 1 (2012)", "Event 2 (2014)"],
    "filtered_insights": "Key time-valid facts extracted strictly adhering to the requested era"
}}
"""


class TemporalReasoningAgent:
    """Validates historical validity and temporal sequencing across evidence."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Executes temporal verification on retrieved evidence."""
        semantic_q = state.get("semantic_query")
        temporal_bounds = semantic_q.temporal_constraints if semantic_q else None
        query = state.get("user_query", "")
        chunks = state.get("chunk_context", [])

        if not temporal_bounds:
            return {"chunk_context": []}

        context_snippet = "\n".join([ch.get("text", "")[:400] for ch in chunks[:4]])

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": TEMPORAL_PROMPT.format(
                    temporal_constraints=json.dumps(temporal_bounds),
                    query=query,
                    context=context_snippet
                )}],
                options={"temperature": 0.0, "num_predict": 512},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            logger.info(f"TemporalReasoning: Verified target period '{parsed.get('target_period')}'.")
            return {
                "chunk_context": [{"temporal_analysis": parsed}]
            }

        except Exception as e:
            logger.info(f"Temporal reasoning check finished ({e}).")
            return {"chunk_context": []}
