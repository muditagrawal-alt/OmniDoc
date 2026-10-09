"""
Embedded LanceDB Vector & Hybrid Storage for OmniDoc.
Provides vector search combined with BM25 full-text search, fused with Reciprocal Rank Fusion.

Document ids used in filter expressions are validated against ``^[A-Za-z0-9_\\-.]+$`` and
quoted, so a crafted id can neither break the SQL filter nor widen a scoped search.
"""
import os
import re
import math
import logging
from typing import List, Dict, Any, Optional

import lancedb

from core.state import RetrievedChunk

logger = logging.getLogger("OmniDoc.LanceDB")

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-.]+$")
RRF_K = 60
# Words the full-text query parser could treat as operators.
_FTS_OPERATORS = {"and", "or", "not", "to"}


def is_safe_id(value: Any) -> bool:
    return isinstance(value, str) and bool(SAFE_ID_RE.match(value))


def _quote(value: str) -> str:
    """SQL string literal (ids are validated first; quotes are doubled defensively)."""
    return "'" + value.replace("'", "''") + "'"


def doc_filter_expr(doc_ids: Optional[List[str]]) -> Optional[str]:
    """
    Builds ``doc_id IN ('a', 'b')`` for valid ids. Returns None for "no filter" (doc_ids
    empty/None) and raises ValueError when ids were given but none is valid, so a scoped
    query can never silently fall back to searching every document.
    """
    if not doc_ids:
        return None
    valid = []
    for did in doc_ids:
        if is_safe_id(did):
            if did not in valid:
                valid.append(did)
        else:
            logger.warning(f"Ignoring invalid document id in filter: {did!r}")
    if not valid:
        raise ValueError("No valid document ids to filter on.")
    return f"doc_id IN ({', '.join(_quote(d) for d in valid)})"


def rrf_fuse(rankings: List[List[str]], k: int = RRF_K) -> Dict[str, float]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1 / (k + rank(d)), rank from 1."""
    fused: Dict[str, float] = {}
    for ranking in rankings:
        seen = set()
        for rank, cid in enumerate(ranking, 1):
            if cid in seen:
                continue
            seen.add(cid)
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return fused


class LanceDBStore:
    """Manages embedded LanceDB tables and hybrid search."""

    def __init__(self, db_dir: str = ".data/lancedb", table_name: str = "document_chunks"):
        self.db_dir = db_dir
        os.makedirs(self.db_dir, exist_ok=True)
        self.table_name = table_name
        self.db = lancedb.connect(self.db_dir)
        self.table = None
        self._fts_ready = False
        self._init_table()

    def _table_exists(self) -> bool:
        try:
            listing = self.db.list_tables()
            names = getattr(listing, "tables", listing)
            return self.table_name in list(names)
        except Exception:
            try:
                return self.table_name in self.db.table_names()
            except Exception:
                return False

    def _init_table(self):
        """Opens the chunks table if it exists (it may also be created later by another instance)."""
        try:
            if self._table_exists():
                self.table = self.db.open_table(self.table_name)
                self._fts_ready = True
                logger.info(f"Connected to LanceDB table '{self.table_name}'.")
            else:
                logger.info(f"LanceDB table '{self.table_name}' will be initialized on first write.")
        except Exception as e:
            logger.error(f"Error accessing LanceDB table: {e}")

    def _ensure_table(self) -> bool:
        if self.table is None:
            self._init_table()
        return self.table is not None

    def _fields(self) -> List[str]:
        try:
            return list(self.table.schema.names) if self.table is not None else []
        except Exception:
            return []

    @property
    def has_search_text(self) -> bool:
        """Tables created by this version keep a search text (title, section, document context + text) for BM25."""
        return "search_text" in self._fields()

    def vector_dim(self) -> Optional[int]:
        try:
            field = self.table.schema.field("vector")
            return int(field.type.list_size)
        except Exception:
            return None

    def _rebuild_fts(self):
        try:
            self.table.create_fts_index("search_text" if self.has_search_text else "text", replace=True)
            self._fts_ready = True
        except Exception as e:
            logger.warning(f"FTS index build skipped: {e}")

    def add_chunks(self, chunks: List[RetrievedChunk], embeddings: List[List[float]],
                   search_texts: Optional[List[str]] = None):
        """
        Adds document chunks and vectors to LanceDB (re-ingesting a document replaces its rows).
        ``search_texts`` (the chunk with its document and section context) feed BM25 when the
        table has that column; ``text`` stays the passage shown and cited.
        """
        if not chunks or not embeddings:
            return
        if len(chunks) != len(embeddings):
            raise ValueError(f"{len(chunks)} chunks but {len(embeddings)} embeddings")

        keep_search = search_texts is not None and (self.table is None and not self._table_exists() or self.has_search_text)
        records = []
        for i, (ch, emb) in enumerate(zip(chunks, embeddings)):
            row = {
                "id": ch.chunk_id,
                "doc_id": ch.doc_id,
                "text": ch.text,
                "page_number": int(ch.page_number or 1),
                "section_title": ch.section_title or "General",
                "vector": [float(x) for x in emb],
            }
            if keep_search:
                row["search_text"] = search_texts[i]
            records.append(row)

        if self._ensure_table():
            # Idempotent re-ingest: drop existing rows of these documents first.
            doc_ids = sorted({r["doc_id"] for r in records})
            try:
                expr = doc_filter_expr(doc_ids)
                if expr:
                    self.table.delete(expr)
            except Exception as e:
                logger.warning(f"Could not clear previous rows for {doc_ids}: {e}")
            self.table.add(records)
        else:
            # Never use mode="overwrite": another store instance may have created the table.
            try:
                self.table = self.db.create_table(self.table_name, data=records)
            except Exception:
                self.table = self.db.open_table(self.table_name)
                self.table.add(records)
        self._rebuild_fts()
        logger.info(f"Indexed {len(records)} chunks into LanceDB.")

    @staticmethod
    def _fts_query(query: str) -> str:
        words = re.findall(r"[A-Za-z0-9]+", query or "")
        return " ".join(w for w in words if w.lower() not in _FTS_OPERATORS)

    def _vector_search(self, query_vector: List[float], limit: int, filter_expr: Optional[str]) -> List[Dict[str, Any]]:
        if not query_vector or not any(query_vector) or any(math.isnan(x) for x in query_vector):
            return []  # failed embedding: cosine distance would be undefined
        builder = self.table.search(query_vector, vector_column_name="vector")
        try:
            builder = builder.distance_type("cosine")
        except AttributeError:
            builder = builder.metric("cosine")
        builder = builder.limit(limit)
        if filter_expr:
            builder = builder.where(filter_expr, prefilter=True)
        return builder.to_pandas().to_dict("records")

    def _fts_search(self, query: str, limit: int, filter_expr: Optional[str]) -> List[Dict[str, Any]]:
        q = self._fts_query(query)
        if not q:
            return []
        if not self._fts_ready:
            self._rebuild_fts()
        builder = self.table.search(q, query_type="fts").limit(limit)
        if filter_expr:
            builder = builder.where(filter_expr, prefilter=True)
        return builder.to_pandas().to_dict("records")

    def hybrid_search(
        self,
        query: str,
        query_vector: List[float],
        top_k: int = 5,
        doc_ids: Optional[List[str]] = None
    ) -> List[RetrievedChunk]:
        """
        Hybrid search: dense vector (cosine) + BM25 full-text, fused with Reciprocal Rank
        Fusion (k=60). ``doc_ids`` restricts both searches to those documents (pre-filter).
        The returned ``score`` is the fused RRF score.
        """
        if not self._ensure_table():
            logger.warning("LanceDB table is empty. Returning 0 results.")
            return []

        try:
            filter_expr = doc_filter_expr(doc_ids)
        except ValueError:
            logger.warning(f"No valid document ids in {doc_ids!r}; returning no results.")
            return []

        pool = max(top_k * 3, 15)
        rows: Dict[str, Dict[str, Any]] = {}
        rankings: List[List[str]] = []

        try:
            vec_rows = self._vector_search(query_vector, pool, filter_expr)
            rankings.append([str(r["id"]) for r in vec_rows])
            for r in vec_rows:
                rows.setdefault(str(r["id"]), r)
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")

        try:
            fts_rows = self._fts_search(query, pool, filter_expr)
            rankings.append([str(r["id"]) for r in fts_rows])
            for r in fts_rows:
                rows.setdefault(str(r["id"]), r)
        except Exception as e:
            logger.warning(f"Full-text search failed: {e}")

        fused = rrf_fuse(rankings)
        ordered = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:top_k]

        results: List[RetrievedChunk] = []
        for cid in ordered:
            row = rows[cid]
            results.append(RetrievedChunk(
                chunk_id=cid,
                doc_id=str(row.get("doc_id", "")),
                text=str(row.get("text", "")),
                page_number=int(row.get("page_number") or 1),
                section_title=str(row.get("section_title") or "General"),
                score=round(fused[cid], 6),
                retrieval_method="hybrid_rrf"
            ))
        return results

    def document_ids(self) -> List[str]:
        """Ids of all indexed documents."""
        if not self._ensure_table():
            return []
        try:
            rows = self.table.search().select(["doc_id"]).limit(10_000_000).to_list()
            return sorted({str(r["doc_id"]) for r in rows if r.get("doc_id")})
        except Exception as e:
            logger.warning(f"Could not list documents: {e}")
            return []

    def get_chunk(self, chunk_id: str) -> Optional[RetrievedChunk]:
        """One chunk by id."""
        if not self._ensure_table() or not is_safe_id(chunk_id):
            return None
        try:
            rows = (self.table.search().where(f"id = {_quote(chunk_id)}", prefilter=True)
                    .select(["id", "doc_id", "text", "page_number", "section_title"]).limit(1).to_list())
        except Exception as e:
            logger.warning(f"Could not read chunk {chunk_id}: {e}")
            return None
        if not rows:
            return None
        r = rows[0]
        return RetrievedChunk(chunk_id=str(r["id"]), doc_id=str(r.get("doc_id", "")), text=str(r.get("text", "")),
                              page_number=int(r.get("page_number") or 1), section_title=str(r.get("section_title") or ""),
                              score=0.0, retrieval_method="lookup")

    def count_chunks(self) -> int:
        """Number of chunks in the whole library."""
        if not self._ensure_table():
            return 0
        try:
            return int(self.table.count_rows())
        except Exception as e:
            logger.warning(f"Could not count chunks: {e}")
            return 0

    def count_document_chunks(self, doc_id: str, cap: int) -> int:
        """Number of chunks of a document, counting no further than ``cap``."""
        if not self._ensure_table() or not is_safe_id(doc_id):
            return 0
        try:
            return len(self.table.search().where(f"doc_id = {_quote(doc_id)}", prefilter=True)
                       .select(["id"]).limit(cap).to_list())
        except Exception as e:
            logger.warning(f"Could not count chunks of {doc_id}: {e}")
            return 0

    def get_document_chunks(self, doc_id: str) -> List[RetrievedChunk]:
        """All chunks of a document in reading order (page, then position on the page)."""
        if not self._ensure_table() or not is_safe_id(doc_id):
            return []
        try:
            rows = (self.table.search()
                    .where(f"doc_id = {_quote(doc_id)}", prefilter=True)
                    .select(["id", "doc_id", "text", "page_number", "section_title"])
                    .limit(100000)
                    .to_list())
        except Exception as e:
            logger.warning(f"Could not read chunks of {doc_id}: {e}")
            return []

        def order(row: Dict[str, Any]):
            m = re.search(r"_c(\d+)$", str(row.get("id", "")))
            return int(row.get("page_number") or 1), int(m.group(1)) if m else 0

        return [RetrievedChunk(
            chunk_id=str(r["id"]),
            doc_id=str(r.get("doc_id", "")),
            text=str(r.get("text", "")),
            page_number=int(r.get("page_number") or 1),
            section_title=str(r.get("section_title") or "General"),
            score=0.0,
            retrieval_method="document_order",
        ) for r in sorted(rows, key=order)]

    def drop_all(self) -> None:
        """Drops the chunks table (used when re-indexing with an embedding model of another size)."""
        try:
            self.db.drop_table(self.table_name)
        except Exception as e:
            logger.warning(f"Could not drop {self.table_name}: {e}")
        self.table = None
        self._fts_ready = False

    def delete_document(self, doc_id: str):
        """Deletes all chunks belonging to a document."""
        if not self._ensure_table():
            return
        if not is_safe_id(doc_id):
            logger.error(f"Refusing to delete with invalid document id {doc_id!r}")
            return
        try:
            self.table.delete(f"doc_id = {_quote(doc_id)}")
            logger.info(f"Deleted chunks for document {doc_id}")
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id} from LanceDB: {e}")
