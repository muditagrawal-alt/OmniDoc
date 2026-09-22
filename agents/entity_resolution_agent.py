"""
Entity Resolution and Disambiguation Agent for OmniDoc.
Resolves ambiguous entity mentions, aliases, and abbreviations to canonical entities in the Knowledge Graph.
"""
import re
import json
import logging
from typing import Dict, Any, List
import ollama

from core.state import AgentWorkflowState, SemanticQuery

logger = logging.getLogger("OmniDoc.EntityResolution")

ENTITY_RESOLUTION_PROMPT = """You are the Entity Resolution Specialist of OmniDoc.
Given the entities extracted from the query and the active context, resolve each entity to its canonical name, disambiguate acronyms, and specify its category.

Rules:
1. "Apple" in business context -> "Apple Inc." (Organization).
2. Resolve acronyms to their full formal name where evident.
3. Output ONLY valid JSON:
{{
    "resolved_entities": [
        {{"mention": "...", "canonical_name": "...", "category": "...", "aliases": ["..."]}}
    ]
}}

EXTRACTED ENTITIES:
{entities}

QUERY CONTEXT:
{query}
"""


class EntityResolutionAgent:
    """Disambiguates and links entity mentions to canonical references."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Resolves entities in semantic query."""
        semantic_q = state.get("semantic_query")
        entities = semantic_q.entities if semantic_q else []
        query = state.get("user_query", "")

        if not entities:
            return {"graph_context": []}

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": ENTITY_RESOLUTION_PROMPT.format(entities=json.dumps(entities), query=query)}],
                options={"temperature": 0.0, "num_predict": 512},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            resolved = parsed.get("resolved_entities", [])
            logger.info(f"EntityResolution: Disambiguated {len(resolved)} entities.")
            
            # Update entity names in semantic query if possible
            if semantic_q and resolved:
                canonical_names = [e.get("canonical_name", e.get("mention")) for e in resolved]
                semantic_q.entities = canonical_names

            return {"graph_context": [{"resolved_entities": resolved}]}

        except Exception as e:
            logger.warning(f"Entity resolution completed with direct match fallback ({e}).")
            return {"graph_context": []}
