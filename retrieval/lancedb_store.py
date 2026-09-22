"""
Embedded LanceDB Vector & Hybrid Storage for OmniDoc.
Provides high-performance vector search combined with BM25 full-text search.
"""
import os
import logging
from typing import List, Dict, Any, Optional
import pyarrow as pa
import lancedb

from core.state import RetrievedChunk

logger = logging.getLogger("OmniDoc.LanceDB")


class LanceDBStore:
    """Manages embedded LanceDB tables and hybrid search."""

    def __init__(self, db_dir: str = ".data/lancedb", table_name: str = "document_chunks"):
        self.db_dir = db_dir
        os.makedirs(self.db_dir, exist_ok=True)
        self.table_name = table_name
        self.db = lancedb.connect(self.db_dir)
        self.table = None
        self._init_table()

    def _init_table(self):
        """Opens or initializes the chunks table."""
        try:
            if self.table_name in self.db.table_names():
                self.table = self.db.open_table(self.table_name)
                logger.info(f"Connected to LanceDB table '{self.table_name}'.")
            else:
                logger.info(f"LanceDB table '{self.table_name}' will be initialized on first write.")
        except Exception as e:
            logger.error(f"Error accessing LanceDB table: {e}")

    def add_chunks(self, chunks: List[RetrievedChunk], embeddings: List[List[float]]):
        """Adds document chunks and vectors to LanceDB."""
        if not chunks or not embeddings:
            return

        records = []
        for ch, emb in zip(chunks, embeddings):
            records.append({
                "id": ch.chunk_id,
                "doc_id": ch.doc_id,
                "text": ch.text,
                "page_number": int(ch.page_number),
                "section_title": ch.section_title or "General",
                "vector": emb
            })

        if self.table is None:
            self.table = self.db.create_table(self.table_name, data=records, mode="overwrite")
            try:
                self.table.create_fts_index("text", replace=True)
                logger.info("Created Tantivy FTS full-text search index on 'text'.")
            except Exception as e:
                logger.warning(f"FTS index creation skipped: {e}")
        else:
            self.table.add(records)
            try:
                self.table.create_fts_index("text", replace=True)
            except Exception:
                pass

        logger.info(f"Successfully indexed {len(records)} chunks into LanceDB.")

    def hybrid_search(
        self,
        query: str,
        query_vector: List[float],
        top_k: int = 5,
        doc_ids: Optional[List[str]] = None
    ) -> List[RetrievedChunk]:
        """
        Executes hybrid search (BM25 lexical + dense vector) with RRF fusion.
        Falls back to pure vector search if FTS is unavailable.
        """
        if self.table is None:
            logger.warning("LanceDB table is empty. Returning 0 results.")
            return []

        results: List[RetrievedChunk] = []
        try:
            # Try native hybrid search first
            builder = self.table.search(query, query_type="hybrid").vector(query_vector).limit(top_k * 2)
            if doc_ids:
                filter_expr = " OR ".join([f"doc_id = '{did}'" for did in doc_ids])
                builder = builder.where(filter_expr)
            df = builder.to_pandas()
        except Exception as e:
            logger.info(f"Hybrid search fallback to vector-only ({e})")
            builder = self.table.search(query_vector).metric("cosine").limit(top_k * 2)
            if doc_ids:
                filter_expr = " OR ".join([f"doc_id = '{did}'" for did in doc_ids])
                builder = builder.where(filter_expr)
            df = builder.to_pandas()

        for _, row in df.iterrows():
            score = 1.0 - float(row.get("_distance", 0.5)) if "_distance" in row else float(row.get("_relevance_score", 0.7))
            results.append(RetrievedChunk(
                chunk_id=str(row["id"]),
                doc_id=str(row["doc_id"]),
                text=str(row["text"]),
                page_number=int(row["page_number"]),
                section_title=str(row.get("section_title", "General")),
                score=score,
                retrieval_method="hybrid"
            ))

        return results[:top_k]

    def delete_document(self, doc_id: str):
        """Deletes all chunks belonging to a document."""
        if self.table is not None:
            try:
                self.table.delete(f"doc_id = '{doc_id}'")
                logger.info(f"Deleted chunks for document {doc_id}")
            except Exception as e:
                logger.error(f"Failed to delete document {doc_id} from LanceDB: {e}")
