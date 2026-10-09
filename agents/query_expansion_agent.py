"""
Query Expansion and Rewriting Agent for OmniDoc.
Generates retrieval query variants and keyword stems. The variants are stored on the
semantic query (``constraints["retrieval_variants"]``) and consumed by the hybrid
retrieval agent; nothing is written into ``chunk_context`` (which holds real passages only).
"""
import json
import time
import logging
from typing import Dict, Any, List

from core.state import AgentWorkflowState
from agents.llm_utils import chat_json, as_str_list, trace

logger = logging.getLogger("OmniDoc.QueryExpansion")

EXPANSION_PROMPT = """You are the Search Query Expansion Specialist of OmniDoc.
Given the user's semantic query, generate retrieval variants that could match wording used in the documents:
1. "dense_queries": 2 alternative phrasings of the core information need.
2. "keyword_stems": 3-6 exact domain keywords for BM25 full-text search.
3. "graph_concepts": key concepts for relationship lookup.
Do not add facts, names or numbers that are not in the query.

Output format (strict JSON):
{{"dense_queries": ["...", "..."], "keyword_stems": ["..."], "graph_concepts": ["..."]}}

SEMANTIC QUERY:
{query_json}
"""


class QueryExpansionAgent:
    """Generates multi-query search variants to reduce retrieval recall blind spots."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    @staticmethod
    def variants_from(understanding: Dict[str, Any], resolved_query: str, canonical_names: List[str]) -> List[str]:
        """
        Retrieval variants without a model call: the English search queries of the
        understanding step (cross-lingual search for questions in other languages), a
        keyword query, and the question with entity mentions replaced by the graph's names.
        """
        from agents.understanding_agent import content_words
        variants = [q for q in understanding.get("search_queries") or [] if isinstance(q, str)]
        words = content_words(" ".join([resolved_query] + variants[:1]))
        if len(words) >= 3:
            variants.append(" ".join(dict.fromkeys(w.lower() for w in words))[:200])
        extra = [n for n in canonical_names if n.lower() not in resolved_query.lower()]
        if extra:
            variants.append(resolved_query + " " + " ".join(extra[:3]))
        seen, out = {resolved_query.strip().lower()}, []
        for v in variants:
            key = v.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(v.strip())
        return out[:4]

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Expands the query into retrieval variants."""
        started = time.perf_counter()
        semantic_q = state.get("semantic_query")
        query_text = state.get("user_query", "")
        if semantic_q is None:
            return {"agent_traces": [trace("query_expansion", "skipped", "No semantic query.", started)]}
        try:
            sq_dict = {k: v for k, v in semantic_q.model_dump().items()
                       if k in ("resolved_query", "goal", "entities", "attributes", "sub_questions")}
            parsed = chat_json(self.model_name, EXPANSION_PROMPT.format(query_json=json.dumps(sq_dict)),
                               temperature=0.2, num_predict=400)
        except Exception as e:
            logger.info(f"Query expansion fallback ({e}). Using raw query.")
            return {"agent_traces": [trace("query_expansion", "failed", str(e)[:200], started)]}

        parsed = parsed if isinstance(parsed, dict) else {}
        dense = as_str_list(parsed.get("dense_queries"), max_items=2, max_len=300)
        stems = as_str_list(parsed.get("keyword_stems"), max_items=6, max_len=60)
        variants = dense + ([" ".join(stems)] if stems else [])
        variants = [v for v in variants if v.strip().lower() != query_text.strip().lower()]
        constraints = dict(semantic_q.constraints or {})
        constraints["retrieval_variants"] = variants[:3]
        logger.info(f"QueryExpansion: {len(dense)} dense variants, {len(stems)} keyword stems.")
        return {
            "semantic_query": semantic_q.model_copy(update={"constraints": constraints}),
            "agent_traces": [trace("query_expansion", "completed", f"{len(variants)} retrieval variants", started)],
        }
