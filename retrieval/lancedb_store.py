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
        Executes true hybrid search combining BM25 lexical search (Tantivy FTS) and
        dense vector search with Reciprocal Rank Fusion (RRF).
        """
        if self.table is None:
            logger.warning("LanceDB table is empty. Returning 0 results.")
            return []

        filter_expr = " OR ".join([f"doc_id = '{did}'" for did in doc_ids]) if doc_ids else None

        # 1. Dense Vector Search
        vec_candidates: Dict[str, Dict[str, Any]] = {}
        try:
            vec_builder = self.table.search(query_vector).metric("cosine").limit(top_k * 2)
            if filter_expr:
                vec_builder = vec_builder.where(filter_expr)
            vec_df = vec_builder.to_pandas()
            for rank, (_, row) in enumerate(vec_df.iterrows(), 1):
                cid = str(row["id"])
                vec_candidates[cid] = {
                    "row": row,
                    "vec_rank": rank,
                    "score": 1.0 - float(row.get("_distance", 0.5))
                }
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")

        # 2. BM25 Lexical Full-Text Search (Tantivy FTS)
        fts_candidates: Dict[str, Dict[str, Any]] = {}
        clean_kw = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
        if clean_kw:
            try:
                fts_builder = self.table.search(clean_kw, query_type="fts").limit(top_k * 2)
                if filter_expr:
                    fts_builder = fts_builder.where(filter_expr)
                fts_df = fts_builder.to_pandas()
                for rank, (_, row) in enumerate(fts_df.iterrows(), 1):
                    cid = str(row["id"])
                    fts_candidates[cid] = {
                        "row": row,
                        "fts_rank": rank,
                        "score": float(row.get("_score", 1.0))
                    }
            except Exception as e:
                logger.debug(f"FTS search notice: {e}")

        # 3. Reciprocal Rank Fusion (RRF: 1 / (60 + rank))
        rrf_scores: Dict[str, float] = {}
        all_cids = set(vec_candidates.keys()).union(set(fts_candidates.keys()))
        for cid in all_cids:
            score = 0.0
            if cid in vec_candidates:
                score += 1.0 / (60 + vec_candidates[cid]["vec_rank"])
            if cid in fts_candidates:
                score += 1.0 / (60 + fts_candidates[cid]["fts_rank"])
            rrf_scores[cid] = score

        # Sort by fused score
        sorted_cids = sorted(all_cids, key=lambda c: rrf_scores[c], reverse=True)

        results: List[RetrievedChunk] = []
        for cid in sorted_cids[:top_k]:
            data = vec_candidates.get(cid) or fts_candidates.get(cid)
            row = data["row"]
            results.append(RetrievedChunk(
                chunk_id=str(row["id"]),
                doc_id=str(row["doc_id"]),
                text=str(row["text"]),
                page_number=int(row["page_number"]),
                section_title=str(row.get("section_title", "General")),
                score=round(rrf_scores[cid] * 60, 4),
                retrieval_method="hybrid_rrf"
            ))

        return results

    def delete_document(self, doc_id: str):
        """Deletes all chunks belonging to a document."""
        if self.table is not None:
            try:
                self.table.delete(f"doc_id = '{doc_id}'")
                logger.info(f"Deleted chunks for document {doc_id}")
            except Exception as e:
                logger.error(f"Failed to delete document {doc_id} from LanceDB: {e}")
