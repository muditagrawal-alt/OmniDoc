"""
Embedded Knowledge Graph Store using Kùzu.
Provides Cypher querying, entity-relation persistence, and multi-hop graph traversal.
"""
import os
import logging
import threading
from typing import List, Dict, Any, Optional
from graph.schema import KUZU_NODE_SCHEMAS, KUZU_REL_SCHEMAS

logger = logging.getLogger("OmniDoc.KuzuStore")


class KuzuGraphStore:
    """Manages the embedded Kùzu property graph database."""

    def __init__(self, db_path: str = ".data/kuzu_db/graph.kuzu"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = None
        self.conn = None
        # One connection is shared by request threads and background extraction.
        self._lock = threading.RLock()
        self._init_db()

    def _exec(self, query: str, params: Optional[Dict[str, Any]] = None):
        with self._lock:
            if params is None:
                return self.conn.execute(query)
            return self.conn.execute(query, params)

    def _init_db(self):
        """Initializes connection and bootstraps schema DDL."""
        try:
            import kuzu
            self.db = kuzu.Database(self.db_path)
            self.conn = kuzu.Connection(self.db)
            self._apply_schema()
            logger.info(f"Connected to embedded Kùzu DB at {self.db_path}")
        except ImportError:
            logger.warning("Kùzu package not installed yet. Graph database operates in stub/in-memory mode.")
        except Exception as e:
            logger.error(f"Error initializing Kùzu database: {e}")

    def _apply_schema(self):
        """Executes DDL statements for nodes and relations."""
        if not self.conn:
            return
        for stmt in KUZU_NODE_SCHEMAS:
            try:
                self._exec(stmt)
            except Exception as e:
                # Table might already exist
                pass

        for stmt in KUZU_REL_SCHEMAS:
            try:
                self._exec(stmt)
            except Exception as e:
                pass

    def add_document(self, doc_id: str, title: str, doc_type: str, doc_hash: str):
        if not self.conn:
            return
        query = """
        MERGE (d:Document {id: $id})
        SET d.title = $title, d.doc_type = $doc_type, d.hash = $hash
        """
        try:
            self._exec(query, {"id": doc_id, "title": title, "doc_type": doc_type, "hash": doc_hash})
        except Exception as e:
            logger.error(f"Failed to add document node {doc_id}: {e}")

    def delete_document(self, doc_id: str):
        """Removes a document, its chunks, and entities no other document still mentions."""
        if not self.conn:
            return
        params = {"doc": doc_id}
        try:
            self._exec("MATCH (c:Chunk) WHERE c.doc_id = $doc DETACH DELETE c", params)
            # Entities are merged by id across documents; keep any still mentioned elsewhere.
            self._exec(
                "MATCH (e:Entity) WHERE e.doc_id = $doc "
                "AND NOT EXISTS { MATCH (:Chunk)-[:MENTIONS]->(e) } DETACH DELETE e",
                params,
            )
            self._exec("MATCH (d:Document) WHERE d.id = $doc DETACH DELETE d", params)
            logger.info(f"Deleted document {doc_id} and related nodes from Kùzu graph.")
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id} from Kùzu: {e}")

    def add_chunk(self, chunk_id: str, doc_id: str, page_number: int, section_title: str, text: str):
        if not self.conn:
            return
        query = """
        MERGE (c:Chunk {id: $id})
        SET c.doc_id = $doc_id, c.page_number = $page_number, c.section_title = $section_title, c.text = $text
        """
        try:
            self._exec(query, {
                "id": chunk_id,
                "doc_id": doc_id,
                "page_number": int(page_number),
                "section_title": section_title or "General",
                "text": text[:2000]
            })
            # Link Document -> Chunk (MERGE keeps re-ingestion idempotent)
            self._exec(
                "MATCH (d:Document {id: $doc}), (c:Chunk {id: $chunk}) MERGE (d)-[:HAS_CHUNK]->(c)",
                {"doc": doc_id, "chunk": chunk_id},
            )
        except Exception as e:
            logger.error(f"Failed to add chunk {chunk_id}: {e}")

    def add_entity(self, entity_id: str, name: str, category: str, description: str, doc_id: str):
        if not self.conn:
            return
        query = """
        MERGE (e:Entity {id: $id})
        SET e.name = $name, e.category = $category, e.description = $description, e.doc_id = $doc_id
        """
        try:
            self._exec(query, {
                "id": entity_id,
                "name": name,
                "category": category,
                "description": description or "",
                "doc_id": doc_id
            })
        except Exception as e:
            logger.error(f"Failed to add entity {name}: {e}")

    def add_relation(self, source_id: str, target_id: str, relation: str, description: str = "", weight: float = 1.0):
        if not self.conn:
            return
        query = (
            "MATCH (s:Entity {id: $sid}), (t:Entity {id: $tid}) "
            "MERGE (s)-[r:RELATES_TO {relation: $rel}]->(t) "
            "ON CREATE SET r.description = $rdesc, r.weight = $weight "
            "ON MATCH SET r.description = $rdesc, r.weight = $weight"
        )
        try:
            self._exec(query, {
                "sid": source_id,
                "tid": target_id,
                "rel": relation,
                "rdesc": description or "",
                "weight": float(weight),
            })
        except Exception as e:
            logger.error(f"Failed to add relation {source_id} -> {target_id}: {e}")

    def link_chunk_to_entity(self, chunk_id: str, entity_id: str):
        if not self.conn:
            return
        try:
            self._exec(
                "MATCH (c:Chunk {id: $cid}), (e:Entity {id: $eid}) MERGE (c)-[:MENTIONS]->(e)",
                {"cid": chunk_id, "eid": entity_id},
            )
        except Exception as e:
            logger.debug(f"Failed to link chunk {chunk_id} -> entity {entity_id}: {e}")

    def query_neighborhood(self, entity_names: List[str], hops: int = 1) -> Dict[str, Any]:
        """
        Returns the 1-hop or 2-hop graph neighborhood around target entities.
        """
        if not self.conn or not entity_names:
            return {"nodes": [], "edges": []}

        results = {"nodes": [], "edges": []}
        seen_nodes = set()
        seen_edges = set()

        for name in entity_names:
            cypher = """
            MATCH (s:Entity)-[r:RELATES_TO]->(t:Entity)
            WHERE toLower(s.name) CONTAINS toLower($name) OR toLower(t.name) CONTAINS toLower($name)
            RETURN s.id, s.name, s.category, s.description,
                   r.relation, r.description,
                   t.id, t.name, t.category, t.description
            LIMIT 25
            """
            try:
                cursor = self._exec(cypher, {"name": name.strip()})
                while cursor.has_next():
                    row = cursor.get_next()
                    s_id, s_name, s_cat, s_desc, rel, r_desc, t_id, t_name, t_cat, t_desc = row
                    
                    if s_id not in seen_nodes:
                        seen_nodes.add(s_id)
                        results["nodes"].append({"id": s_id, "name": s_name, "category": s_cat, "description": s_desc})
                        
                    if t_id not in seen_nodes:
                        seen_nodes.add(t_id)
                        results["nodes"].append({"id": t_id, "name": t_name, "category": t_cat, "description": t_desc})

                    edge_key = (s_id, t_id, rel)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        results["edges"].append({
                            "source": s_id,
                            "source_name": s_name,
                            "target": t_id,
                            "target_name": t_name,
                            "relation": rel,
                            "description": r_desc
                        })
            except Exception as e:
                logger.error(f"Error querying neighborhood for {name}: {e}")

        return results

    def multi_hop_traversal(self, source_name: str, target_name: str, max_hops: int = 3) -> List[Dict[str, Any]]:
        """Finds paths connecting two distant entities across the graph."""
        if not self.conn:
            return []
        cypher = f"""
        MATCH p = (s:Entity)-[:RELATES_TO*1..{max_hops}]->(t:Entity)
        WHERE toLower(s.name) = toLower($source) AND toLower(t.name) = toLower($target)
        RETURN p
        LIMIT 5
        """
        paths = []
        try:
            cursor = self._exec(cypher, {"source": source_name, "target": target_name})
            while cursor.has_next():
                paths.append(str(cursor.get_next()[0]))
        except Exception as e:
            logger.error(f"Error in multi-hop traversal: {e}")
        return paths

    def get_all_graph(self, limit: int = 2000) -> Dict[str, Any]:
        """
        Returns entities, relations and source documents for the knowledge globe.
        `limit` caps the number of entities; relations are returned only between
        returned entities.
        """
        results: Dict[str, Any] = {"nodes": [], "edges": [], "documents": []}
        if not self.conn:
            return results
        limit = max(1, min(int(limit), 20000))
        try:
            node_ids = set()
            cursor = self._exec(
                f"MATCH (e:Entity) RETURN e.id, e.name, e.category, e.description, e.doc_id "
                f"ORDER BY e.name LIMIT {limit}"
            )
            while cursor.has_next():
                e_id, e_name, e_cat, e_desc, e_doc = cursor.get_next()
                if not e_id or e_id in node_ids:
                    continue
                node_ids.add(e_id)
                results["nodes"].append({
                    "id": e_id,
                    "name": e_name or e_id,
                    "category": e_cat or "Entity",
                    "description": e_desc or "",
                    "doc_id": e_doc or "",
                })

            seen_edges = set()
            cursor = self._exec(
                "MATCH (s:Entity)-[r:RELATES_TO]->(t:Entity) "
                "RETURN s.id, s.name, r.relation, r.description, t.id, t.name"
            )
            while cursor.has_next():
                s_id, s_name, rel, r_desc, t_id, t_name = cursor.get_next()
                if s_id not in node_ids or t_id not in node_ids:
                    continue
                key = (s_id, t_id, rel)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                results["edges"].append({
                    "source": s_id,
                    "source_name": s_name,
                    "target": t_id,
                    "target_name": t_name,
                    "relation": rel or "RELATED_TO",
                    "description": r_desc or "",
                })

            cursor = self._exec("MATCH (d:Document) RETURN d.id, d.title ORDER BY d.title")
            while cursor.has_next():
                d_id, d_title = cursor.get_next()
                results["documents"].append({"id": d_id, "title": d_title or d_id})
        except Exception as e:
            logger.error(f"Error fetching all graph: {e}")
        return results

    def entity_counts_by_document(self) -> Dict[str, int]:
        """Number of extracted entities per document id."""
        counts: Dict[str, int] = {}
        if not self.conn:
            return counts
        try:
            cursor = self._exec("MATCH (e:Entity) RETURN e.doc_id, count(*)")
            while cursor.has_next():
                doc_id, n = cursor.get_next()
                if doc_id:
                    counts[doc_id] = int(n)
        except Exception as e:
            logger.warning(f"Could not count entities per document: {e}")
        return counts

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Returns one entity with its direct relations (both directions)."""
        if not self.conn:
            return None
        try:
            cursor = self._exec(
                "MATCH (e:Entity) WHERE e.id = $id RETURN e.id, e.name, e.category, e.description, e.doc_id",
                {"id": node_id},
            )
            if not cursor.has_next():
                return None
            e_id, e_name, e_cat, e_desc, e_doc = cursor.get_next()
            node = {"id": e_id, "name": e_name, "category": e_cat or "Entity", "description": e_desc or "", "doc_id": e_doc or ""}
            edges = []
            cursor = self._exec(
                "MATCH (s:Entity)-[r:RELATES_TO]->(t:Entity) WHERE s.id = $id OR t.id = $id "
                "RETURN s.id, s.name, r.relation, r.description, t.id, t.name",
                {"id": node_id},
            )
            while cursor.has_next():
                s_id, s_name, rel, r_desc, t_id, t_name = cursor.get_next()
                edges.append({"source": s_id, "source_name": s_name, "target": t_id, "target_name": t_name,
                              "relation": rel, "description": r_desc or ""})
            return {"node": node, "edges": edges}
        except Exception as e:
            logger.error(f"Error fetching node {node_id}: {e}")
            return None
