"""
Query Expansion and Rewriting Agent for OmniDoc.
Generates multi-query variants, keyword stems for Tantivy BM25,
and relationship traversal concepts for the Knowledge Graph.
"""
import re
import json
import logging
from typing import Dict, Any, List
import ollama

from core.state import AgentWorkflowState, SemanticQuery

logger = logging.getLogger("OmniDoc.QueryExpansion")

EXPANSION_PROMPT = """You are the Search Query Expansion Specialist of OmniDoc.
Given the user's semantic query, generate diverse, high-signal retrieval query variants:
1. "dense_queries": 2 semantic variations phrasing the core information need.
2. "keyword_stems": 3-6 exact domain keywords for BM25 full-text search.
3. "graph_concepts": Key concept pairs for relationship pathfinding.

Output format (strict JSON):
{{
    "dense_queries": ["query variant 1", "query variant 2"],
    "keyword_stems": ["keyword1", "keyword2", "keyword3"],
    "graph_concepts": ["conceptA", "conceptB"]
}}

SEMANTIC QUERY:
{query_json}
"""


class QueryExpansionAgent:
    """Generates multi-query search variants to eliminate retrieval recall blindspots."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Expands query into multi-format retrieval variants."""
        semantic_q = state.get("semantic_query")
        query_text = state.get("user_query", "")

        try:
            sq_dict = semantic_q.model_dump() if semantic_q else {"raw_query": query_text}
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": EXPANSION_PROMPT.format(query_json=json.dumps(sq_dict))}],
                options={"temperature": 0.2, "num_predict": 512},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            logger.info(f"QueryExpansion: Generated {len(parsed.get('dense_queries', []))} dense variants and {len(parsed.get('keyword_stems', []))} BM25 stems.")
            return {
                "chunk_context": [{"query_expansion": parsed}]
            }

        except Exception as e:
            logger.info(f"Query expansion fallback ({e}). Using raw query.")
            return {"chunk_context": []}
