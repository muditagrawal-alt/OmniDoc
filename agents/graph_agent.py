"""
Knowledge Graph Agent Node for LangGraph.
Queries the embedded Kùzu property graph for entity neighborhoods,
cross-document relationships, and multi-hop paths.
"""
import logging
from typing import Dict, Any, List
from core.state import AgentWorkflowState, GraphSubGraph, EntityNode, RelationshipEdge
from graph.store import KuzuGraphStore

logger = logging.getLogger("OmniDoc.GraphAgent")


class GraphAgent:
    """Navigates entity relationships and subgraphs in Kùzu."""

    def __init__(self, graph_store: KuzuGraphStore):
        self.graph_store = graph_store

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Executes graph queries based on extracted entities and sub-questions.
        """
        intent = state.get("intent")
        entities = []
        if intent and intent.entities_mentioned:
            entities = intent.entities_mentioned
        else:
            # Fallback: extract potential noun terms from query
            query = state.get("user_query", "")
            words = [w for w in query.split() if len(w) > 4 and w.isalnum()]
            entities = words[:4]

        logger.info(f"GraphAgent exploring neighborhood for entities: {entities}")
        neighborhood = self.graph_store.query_neighborhood(entities, hops=2)
        
        nodes = [EntityNode(
            id=n["id"],
            name=n["name"],
            category=n["category"],
            description=n.get("description", ""),
            doc_id=""
        ) for n in neighborhood.get("nodes", [])]

        edges = [RelationshipEdge(
            source_id=e["source"],
            target_id=e["target"],
            relation=e["relation"],
            description=e.get("description", ""),
            weight=1.0,
            doc_id=""
        ) for e in neighborhood.get("edges", [])]

        subgraph_dict = {
            "source": "kuzu_property_graph",
            "entities_queried": entities,
            "nodes": [n.model_dump() for n in nodes],
            "edges": [e.model_dump() for e in edges],
            "node_count": len(nodes),
            "edge_count": len(edges)
        }

        return {"graph_context": [subgraph_dict]}
