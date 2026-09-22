"""
Embedded Knowledge Graph Store using Kùzu.
Provides Cypher querying, entity-relation persistence, and multi-hop graph traversal.
"""
import os
import logging
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
        self._init_db()

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
                self.conn.execute(stmt)
            except Exception as e:
                # Table might already exist
                pass

        for stmt in KUZU_REL_SCHEMAS:
            try:
                self.conn.execute(stmt)
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
            self.conn.execute(query, {"id": doc_id, "title": title, "doc_type": doc_type, "hash": doc_hash})
        except Exception as e:
            logger.error(f"Failed to add document node {doc_id}: {e}")

    def add_chunk(self, chunk_id: str, doc_id: str, page_number: int, section_title: str, text: str):
        if not self.conn:
            return
        query = """
        MERGE (c:Chunk {id: $id})
        SET c.doc_id = $doc_id, c.page_number = $page_number, c.section_title = $section_title, c.text = $text
        """
        try:
            self.conn.execute(query, {
                "id": chunk_id,
                "doc_id": doc_id,
                "page_number": int(page_number),
                "section_title": section_title or "General",
                "text": text[:2000]
            })
            # Link Document -> Chunk
            safe_did = doc_id.replace('"', '\\"')
            safe_cid = chunk_id.replace('"', '\\"')
            link_q = f'MATCH (d:Document {{id: "{safe_did}"}}), (c:Chunk {{id: "{safe_cid}"}}) CREATE (d)-[:HAS_CHUNK]->(c);'
            self.conn.execute(link_q)
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
            self.conn.execute(query, {
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
        safe_sid = source_id.replace('"', '\\"')
        safe_tid = target_id.replace('"', '\\"')
        safe_rel = relation.replace('"', '\\"')
        safe_desc = (description or "").replace('"', '\\"')
        safe_weight = float(weight)
        query = f'MATCH (s:Entity {{id: "{safe_sid}"}}), (t:Entity {{id: "{safe_tid}"}}) CREATE (s)-[r:RELATES_TO {{relation: "{safe_rel}", description: "{safe_desc}", weight: {safe_weight}}}]->(t);'
        try:
            self.conn.execute(query)
        except Exception as e:
            logger.error(f"Failed to add relation {source_id} -> {target_id}: {e}")

    def link_chunk_to_entity(self, chunk_id: str, entity_id: str):
        if not self.conn:
            return
        safe_cid = chunk_id.replace('"', '\\"')
        safe_eid = entity_id.replace('"', '\\"')
        query = f'MATCH (c:Chunk {{id: "{safe_cid}"}}), (e:Entity {{id: "{safe_eid}"}}) CREATE (c)-[:MENTIONS]->(e);'
        try:
            self.conn.execute(query)
        except Exception as e:
            pass

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
                cursor = self.conn.execute(cypher, {"name": name.strip()})
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
            cursor = self.conn.execute(cypher, {"source": source_name, "target": target_name})
            while cursor.has_next():
                paths.append(str(cursor.get_next()[0]))
        except Exception as e:
            logger.error(f"Error in multi-hop traversal: {e}")
        return paths
