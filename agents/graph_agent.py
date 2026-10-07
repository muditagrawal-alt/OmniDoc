"""
Knowledge Graph Agent Node for LangGraph.
Queries the embedded Kùzu property graph for relations around the query's entities,
restricted to the documents selected for the query, and attaches provenance (doc_id,
chunk_id, page, section of a chunk that mentions the source entity) to every edge.
"""
import re
import time
import logging
from typing import Dict, Any, List, Optional

from core.state import AgentWorkflowState
from graph.store import KuzuGraphStore
from agents.llm_utils import trace

logger = logging.getLogger("OmniDoc.GraphAgent")

MAX_ENTITIES = 6
MAX_EDGES = 30
_STOPWORDS = {
    "what", "which", "where", "when", "whose", "about", "there", "their", "these", "those", "would",
    "could", "should", "between", "compare", "explain", "describe", "summarize", "document", "documents",
    "paper", "report", "according", "please", "tell", "much", "many", "does", "with", "from", "into",
}

_NEIGHBORHOOD_CYPHER = """
MATCH (s:Entity)-[r:RELATES_TO]->(t:Entity)
WHERE (toLower(s.name) CONTAINS $name OR toLower(t.name) CONTAINS $name){doc_filter}
OPTIONAL MATCH (c:Chunk)-[:MENTIONS]->(s)
RETURN s.id, s.name, s.category, s.description, s.doc_id,
       r.relation, r.description,
       t.id, t.name, t.category, t.description,
       c.id, c.page_number, c.section_title
LIMIT 80
"""


class GraphAgent:
    """Navigates entity relationships and subgraphs in Kùzu."""

    def __init__(self, graph_store: KuzuGraphStore):
        self.graph_store = graph_store

    @staticmethod
    def _entities(state: AgentWorkflowState) -> List[str]:
        semantic_q = state.get("semantic_query")
        intent = state.get("intent")
        raw: List[str] = []
        if semantic_q is not None:
            raw.extend(getattr(semantic_q, "entities", None) or [])
        if intent is not None:
            raw.extend(getattr(intent, "entities_mentioned", None) or [])
        if not raw:
            query = state.get("user_query", "")
            raw = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", query) if w.lower() not in _STOPWORDS][:4]
        seen, out = set(), []
        for e in raw:
            if not isinstance(e, str):
                continue
            name = " ".join(e.split()).strip()
            key = name.lower()
            # Very short names match almost everything with CONTAINS.
            if len(key) < 3 or key in seen or key in _STOPWORDS:
                continue
            seen.add(key)
            out.append(name)
        return out[:MAX_ENTITIES]

    def _query(self, entities: List[str], doc_ids: List[str]) -> Dict[str, Any]:
        conn = getattr(self.graph_store, "conn", None)
        if conn is None:
            return {"nodes": [], "edges": []}
        doc_filter = " AND list_contains($doc_ids, s.doc_id)" if doc_ids else ""
        cypher = _NEIGHBORHOOD_CYPHER.format(doc_filter=doc_filter)
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: Dict[tuple, Dict[str, Any]] = {}
        for name in entities:
            params: Dict[str, Any] = {"name": name.lower()}
            if doc_ids:
                params["doc_ids"] = list(doc_ids)
            try:
                cursor = conn.execute(cypher, params)
            except Exception as e:
                logger.error(f"Graph neighborhood query failed for {name!r}: {e}")
                continue
            while cursor.has_next():
                (s_id, s_name, s_cat, s_desc, s_doc, rel, r_desc,
                 t_id, t_name, t_cat, t_desc, c_id, c_page, c_section) = cursor.get_next()
                for nid, nname, ncat, ndesc in ((s_id, s_name, s_cat, s_desc), (t_id, t_name, t_cat, t_desc)):
                    if nid not in nodes:
                        nodes[nid] = {"id": nid, "name": nname, "category": ncat or "Concept",
                                      "description": ndesc or "", "doc_id": s_doc or ""}
                key = (s_id, rel, t_id)
                if key in edges:
                    continue
                if len(edges) >= MAX_EDGES:
                    break
                edges[key] = {
                    "source_id": s_id,
                    "target_id": t_id,
                    "source": s_id,
                    "target": t_id,
                    "source_name": s_name,
                    "target_name": t_name,
                    "relation": rel,
                    "description": r_desc or "",
                    "weight": 1.0,
                    "doc_id": s_doc or "",
                    "chunk_id": c_id or "",
                    "page": int(c_page) if c_page else None,
                    "section": c_section or "",
                }
        return {"nodes": list(nodes.values()), "edges": list(edges.values())}

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Executes graph queries based on extracted entities, scoped to the selected documents.
        """
        started = time.perf_counter()
        entities = self._entities(state)
        doc_ids = [d for d in (state.get("document_ids") or []) if isinstance(d, str) and d]
        if not entities:
            return {"agent_traces": [trace("graph_retrieval", "skipped", "No entities to look up.", started)]}

        logger.info(f"GraphAgent exploring neighborhood for entities: {entities} (docs: {doc_ids or 'ALL'})")
        neighborhood = self._query(entities, doc_ids)
        subgraph = {
            "source": "kuzu_property_graph",
            "entities_queried": entities,
            "nodes": neighborhood["nodes"],
            "edges": neighborhood["edges"],
            "node_count": len(neighborhood["nodes"]),
            "edge_count": len(neighborhood["edges"]),
        }
        return {
            "graph_context": [subgraph],
            "agent_traces": [trace("graph_retrieval", "completed",
                                   f"{len(neighborhood['edges'])} relations for {entities}", started)],
        }
