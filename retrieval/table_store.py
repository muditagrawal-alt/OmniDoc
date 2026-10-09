"""
Table store: every table found in a document becomes a SQLite table, so questions about
tables are answered with exact SQL instead of a language model reading flattened text.

Queries run on a separate read-only connection with an authorizer that allows nothing but
reading the tables of the documents in scope, a time limit and a row cap, so a generated
query cannot modify data, attach files or run for long.
"""
import os
import re
import json
import math
import time
import sqlite3
import logging
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("OmniDoc.TableStore")

MAX_RESULT_ROWS = 200
QUERY_TIMEOUT_S = 3.0
_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-.]+$")
_NUM_CLEAN = re.compile(r"[\s,$€£¥₹%]")
_NUMBER = re.compile(r"^\(?[-+−]?\d+(?:\.\d+)?\)?$")

# SQL functions a query may call (aggregates, maths, text and date helpers).
_ALLOWED_FUNCTIONS = {
    "count", "sum", "avg", "min", "max", "total", "group_concat", "abs", "round", "lower", "upper",
    "length", "substr", "substring", "trim", "ltrim", "rtrim", "replace", "instr", "coalesce", "ifnull",
    "nullif", "cast", "printf", "date", "strftime", "julianday", "like", "glob", "iif", "sign",
}


def parse_number(cell: Any) -> Optional[float]:
    """'3,800,000' -> 3800000.0, '(12.5)' -> -12.5, '51%' -> 51.0; None if not a plain number."""
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if math.isfinite(cell) else None
    s = _NUM_CLEAN.sub("", str(cell or "")).replace("−", "-")
    if not s or not _NUMBER.match(s):
        return None
    negative = s.startswith("(") and s.endswith(")")
    try:
        value = float(s.strip("()"))
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return -value if negative else value


def sql_identifier(name: str, used: set) -> str:
    base = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower()).strip("_") or "col"
    if base[0].isdigit():
        base = f"c_{base}"
    candidate, k = base[:48], 2
    while candidate in used:
        candidate = f"{base[:44]}_{k}"
        k += 1
    used.add(candidate)
    return candidate


# Catalog owner of the library-record tables (one row per document, one table per document type).
LIBRARY_DOC_ID = "_library"


class TableStore:
    """SQLite-backed store of document tables with a catalog for search."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS table_catalog ("
                " table_name TEXT PRIMARY KEY, table_id TEXT, doc_id TEXT, page INTEGER, title TEXT,"
                " columns_json TEXT, n_rows INTEGER, bbox_json TEXT, source TEXT)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_doc ON table_catalog(doc_id)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ------------------------------------------------------------------ write
    @staticmethod
    def _write_table(conn: sqlite3.Connection, name: str, doc_id: str, t: Dict[str, Any]) -> bool:
        """(Re)creates one typed table from {"columns", "rows", "title", ...} and catalogs it."""
        columns, rows = t.get("columns") or [], t.get("rows") or []
        if not columns or not rows:
            return False
        used: set = set()
        spec = []
        for j, col in enumerate(columns):
            values = [r[j] if j < len(r) else "" for r in rows]
            filled = [v for v in values if v not in ("", None)]
            numeric = bool(filled) and sum(parse_number(v) is not None for v in filled) >= 0.8 * len(filled)
            spec.append({"name": col, "sql": sql_identifier(col, used), "type": "REAL" if numeric else "TEXT"})
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.execute(f'CREATE TABLE "{name}" (' + ", ".join(f'"{c["sql"]}" {c["type"]}' for c in spec) + ")")
        placeholders = ", ".join("?" for _ in spec)
        conn.executemany(
            f'INSERT INTO "{name}" VALUES ({placeholders})',
            [[(parse_number(r[j]) if c["type"] == "REAL" else str(r[j])) if j < len(r) and r[j] not in ("", None) else None
              for j, c in enumerate(spec)] for r in rows],
        )
        conn.execute(
            "INSERT OR REPLACE INTO table_catalog VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, t.get("table_id") or name, doc_id, t.get("page"), t.get("title") or name,
             json.dumps(spec), len(rows), json.dumps(t.get("bbox")), t.get("source") or ""),
        )
        return True

    def add_tables(self, doc_id: str, tables: Sequence[Dict[str, Any]]) -> int:
        """Replaces a document's tables. Returns how many were stored."""
        if not _SAFE_ID.match(doc_id or ""):
            return 0
        self.delete_document(doc_id)
        stored = 0
        with self._lock, self._connect() as conn:
            for k, t in enumerate(tables, 1):
                if self._write_table(conn, f"t_{re.sub(r'[^0-9a-zA-Z]', '_', doc_id)}_{k}", doc_id, t):
                    stored += 1
        return stored

    def put_table(self, name: str, doc_id: str, table: Dict[str, Any]) -> bool:
        """Creates or replaces one named table (used for library records); drops it when it has no rows."""
        if not re.match(r"^t_[0-9A-Za-z_]+$", name) or not _SAFE_ID.match(doc_id or ""):
            return False
        with self._lock, self._connect() as conn:
            if not table.get("rows"):
                conn.execute(f'DROP TABLE IF EXISTS "{name}"')
                conn.execute("DELETE FROM table_catalog WHERE table_name = ?", (name,))
                return False
            return self._write_table(conn, name, doc_id, table)

    def delete_document(self, doc_id: str) -> None:
        if not _SAFE_ID.match(doc_id or ""):
            return
        with self._lock, self._connect() as conn:
            names = [r[0] for r in conn.execute("SELECT table_name FROM table_catalog WHERE doc_id = ?", (doc_id,))]
            for name in names:
                conn.execute(f'DROP TABLE IF EXISTS "{name}"')
            conn.execute("DELETE FROM table_catalog WHERE doc_id = ?", (doc_id,))

    # ------------------------------------------------------------------ read
    def tables_for(self, doc_ids: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        """Catalog entries (with columns) for the given documents, or all documents (library records excluded)."""
        with self._connect() as conn:
            if doc_ids:
                ids = [d for d in doc_ids if _SAFE_ID.match(d or "")]
                if not ids:
                    return []
                rows = conn.execute(
                    f"SELECT * FROM table_catalog WHERE doc_id IN ({', '.join('?' for _ in ids)}) ORDER BY doc_id, page, table_name",
                    ids,
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM table_catalog WHERE doc_id != ? ORDER BY doc_id, page, table_name",
                                    (LIBRARY_DOC_ID,)).fetchall()
        out = []
        for name, table_id, doc_id, page, title, columns_json, n_rows, bbox_json, source in rows:
            out.append({
                "table": name, "table_id": table_id, "doc_id": doc_id, "page": page, "title": title,
                "columns": json.loads(columns_json or "[]"), "n_rows": n_rows,
                "bbox": json.loads(bbox_json) if bbox_json and bbox_json != "null" else None, "source": source,
            })
        return out

    def counts_by_document(self) -> Dict[str, int]:
        with self._connect() as conn:
            return {doc: n for doc, n in conn.execute("SELECT doc_id, COUNT(*) FROM table_catalog GROUP BY doc_id")}

    def sample_rows(self, table: str, n: int = 3) -> List[Tuple[Any, ...]]:
        if not re.match(r"^t_[0-9A-Za-z_]+$", table):
            return []
        with self._connect() as conn:
            return conn.execute(f'SELECT * FROM "{table}" LIMIT ?', (n,)).fetchall()

    def text_values(self, table: str, limit: int = 400) -> List[str]:
        """Distinct short text cells, used to match question words to a table."""
        info = next((t for t in self.tables_for() if t["table"] == table), None)
        if not info:
            return []
        text_cols = [c["sql"] for c in info["columns"] if c["type"] == "TEXT"]
        if not text_cols:
            return []
        values: List[str] = []
        with self._connect() as conn:
            for col in text_cols[:6]:
                values.extend(str(v) for (v,) in conn.execute(
                    f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL LIMIT ?', (limit,)))
        return values

    def _check_identifiers(self, statement: str, allowed: set) -> None:
        """
        SQLite reads a double-quoted name it does not know as a string literal, so a
        misspelled "column" silently returns its own name on every row. Every quoted name
        must be an allowed table, one of its columns, or an alias or CTE the query defines.
        """
        known = set(allowed)
        if allowed:
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT columns_json FROM table_catalog WHERE lower(table_name) IN ({', '.join('?' for _ in allowed)})",
                    sorted(allowed),
                ).fetchall()
            for (columns_json,) in rows:
                known.update(str(c.get("sql", "")).lower() for c in json.loads(columns_json or "[]"))
        code = re.sub(r"'(?:[^']|'')*'", "''", statement)  # ignore string literals
        known.update(a.lower() for a in re.findall(r'\bAS\s+"([^"]+)"', code, re.IGNORECASE))
        known.update(a.lower() for a in re.findall(r'"([^"]+)"\s*(?:\([^)]*\))?\s+AS\s*\(', code, re.IGNORECASE))
        for name in re.findall(r'"([^"]+)"', code):
            if name.lower() not in known:
                raise ValueError(f"no such column: {name}")

    def run_select(self, sql: str, allowed_tables: Sequence[str], max_rows: int = MAX_RESULT_ROWS,
                   timeout_s: float = QUERY_TIMEOUT_S) -> Dict[str, Any]:
        """
        Runs one read-only SELECT over ``allowed_tables``. Returns {"columns", "rows",
        "truncated"}; raises ValueError with a readable message if the query is refused or fails.
        """
        statement = (sql or "").strip().rstrip(";").strip()
        if not re.match(r"^(select|with)\b", statement, re.IGNORECASE):
            raise ValueError("Only a single SELECT query is allowed.")
        if ";" in statement:
            raise ValueError("Only one statement is allowed.")
        allowed = {t.lower() for t in allowed_tables}
        self._check_identifiers(statement, allowed)

        def authorizer(action, arg1, arg2, _db, _trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ:
                return sqlite3.SQLITE_OK if (arg1 or "").lower() in allowed else sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION:
                return sqlite3.SQLITE_OK if (arg2 or "").lower() in _ALLOWED_FUNCTIONS else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_DENY

        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5.0)
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)
        conn.set_authorizer(authorizer)
        try:
            cur = conn.execute(statement)
            columns = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as e:
            message = str(e)
            if "interrupted" in message:
                message = "The query took too long."
            elif "not authorized" in message or "prohibited" in message:
                message = "The query used a table or function that is not allowed."
            raise ValueError(message) from e
        finally:
            conn.close()
        truncated = len(rows) > max_rows
        return {"columns": columns, "rows": [list(r) for r in rows[:max_rows]], "truncated": truncated}
