"""
Entity Resolution and Disambiguation Agent for OmniDoc.
Resolves entity mentions, aliases and abbreviations in the query to canonical names.

The original mentions are always kept next to the canonical names (a model-expanded acronym
that is wrong must not hide the literal mention from graph lookups). Output:
``semantic_query`` (copy with the merged entity list) and one ``graph_context`` record
``{"source": "entity_resolution", "resolved_entities": [...], "nodes": [], "edges": []}``.
"""
import re
import json
import time
import difflib
import logging
from typing import Dict, Any, List, Optional

from core.state import AgentWorkflowState
from agents.llm_utils import chat_json, as_list, as_str_list, trace

logger = logging.getLogger("OmniDoc.EntityResolution")

ENTITY_RESOLUTION_PROMPT = """You are the Entity Resolution Specialist of OmniDoc.
Given the entities extracted from the user's query, give each one its canonical name and a category.

Rules:
1. Expand an acronym or short name only when its meaning is certain from the query itself; otherwise keep the mention unchanged as the canonical name.
2. Do not add entities that are not mentioned in the query.
3. Output ONLY valid JSON:
{{"resolved_entities": [{{"mention": "...", "canonical_name": "...", "category": "...", "aliases": ["..."]}}]}}

EXTRACTED ENTITIES:
{entities}

QUERY:
{query}
"""


class EntityResolutionAgent:
    """Disambiguates and links entity mentions to canonical references."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct", graph_store: Any = None):
        self.model_name = model_name
        self.graph_store = graph_store

    def resolve_against_graph(self, entities: List[str], doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Links each mention to the knowledge graph's names without a model call: exact or
        case-insensitive matches first, then the closest name above a similarity threshold
        ("US EPA" -> "U.S. Environmental Protection Agency" is left to the graph's own
        CONTAINS search; acronyms of multi-word names are matched here).
        """
        names = self.graph_store.entity_names(doc_ids or None) if self.graph_store is not None else []
        by_lower = {n.lower(): n for n in names}
        resolved = []
        for mention in entities:
            m = mention.strip()
            if not m:
                continue
            key = m.lower()
            canonical, how = by_lower.get(key), "exact"
            if canonical is None and names:
                acronym = {"".join(w[0] for w in re.findall(r"[A-Za-z]+", n) if w[0].isupper()).lower(): n
                           for n in names if len(n.split()) > 1}
                canonical, how = acronym.get(key) if m.isupper() and len(m) >= 2 else None, "acronym"
                if canonical is None:
                    close = difflib.get_close_matches(key, list(by_lower), n=1, cutoff=0.86)
                    canonical, how = (by_lower[close[0]], "similar") if close else (None, "")
            resolved.append({"mention": m[:120], "canonical_name": (canonical or m)[:120], "category": "Concept",
                             "aliases": [], "matched": how if canonical else "none"})
        return resolved

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Resolves entities in the semantic query."""
        started = time.perf_counter()
        semantic_q = state.get("semantic_query")
        entities = [e for e in (getattr(semantic_q, "entities", None) or []) if isinstance(e, str) and e.strip()]
        query = state.get("user_query", "")
        if not entities:
            return {"agent_traces": [trace("entity_resolution", "skipped", "No entities in query.", started)]}

        try:
            parsed = chat_json(
                self.model_name,
                ENTITY_RESOLUTION_PROMPT.format(entities=json.dumps(entities), query=query),
                num_predict=512,
            )
        except Exception as e:
            logger.warning(f"Entity resolution unavailable ({e}); using mentions as-is.")
            return {"agent_traces": [trace("entity_resolution", "failed", str(e)[:200], started)]}

        raw = parsed.get("resolved_entities", []) if isinstance(parsed, dict) else parsed
        resolved: List[Dict[str, Any]] = []
        for r in as_list(raw):
            if isinstance(r, str):
                r = {"mention": r, "canonical_name": r}
            if not isinstance(r, dict):
                continue
            mention = str(r.get("mention") or r.get("canonical_name") or "").strip()
            canonical = str(r.get("canonical_name") or mention).strip()
            if not mention or not canonical:
                continue
            resolved.append({
                "mention": mention[:120],
                "canonical_name": canonical[:120],
                "category": str(r.get("category") or "Concept")[:60],
                "aliases": as_str_list(r.get("aliases"), max_items=6, max_len=120),
            })

        merged, seen = [], set()
        for name in entities + [r["canonical_name"] for r in resolved]:
            key = name.lower()
            if key not in seen:
                seen.add(key)
                merged.append(name)

        logger.info(f"EntityResolution: resolved {len(resolved)} entities -> {merged}")
        out: Dict[str, Any] = {
            "graph_context": [{"source": "entity_resolution", "resolved_entities": resolved, "nodes": [], "edges": []}],
            "agent_traces": [trace("entity_resolution", "completed", f"{len(resolved)} entities resolved", started)],
        }
        if semantic_q is not None:
            out["semantic_query"] = semantic_q.model_copy(update={"entities": merged[:12]})
        return out
