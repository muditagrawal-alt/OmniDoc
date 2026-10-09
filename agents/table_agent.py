"""
Table question answering with SQL.

Picks the tables of the documents in scope that match the question (title, column names
and cell values), asks the local model for one to three read-only SQLite SELECTs over them
(one per part of a multi-part question), runs them in the table store's locked-down
connection (one retry with the error messages if they fail) and returns the results as
evidence the answer can cite. A small table is also returned whole, so the answer and the
verifier can check every row rather than trusting a query a small model wrote.
"""
import re
import time
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.state import AgentWorkflowState
from agents.llm_utils import chat_json, trace
from retrieval.table_store import TableStore

logger = logging.getLogger("OmniDoc.TableAgent")

MAX_TABLES = 3
MAX_QUERIES = 3
RESULT_ROWS_IN_EVIDENCE = 20
# A single shared header word ("share" in "what themes do they share?") is not enough.
MIN_SCORE = 3.0
HINT_MIN_SIMILARITY = 0.55
HINT_SPREAD = 0.12
# Tables up to this size are also given to the writer in full.
SMALL_TABLE_ROWS = 30
_TEXT_MATCH = re.compile(r"\b(?:I?LIKE|GLOB|INSTR)\b", re.I)
SMALL_TABLE_COLUMNS = 10

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "and", "for", "with", "what", "which", "who", "how", "many", "much", "are", "was", "were", "this",
    "that", "these", "those", "from", "into", "than", "then", "does", "did", "have", "has", "had", "per", "all",
    "each", "list", "show", "give", "tell", "about", "between", "their", "there", "they", "its", "our", "your",
    "document", "documents", "report", "please", "value", "values",
}
_TABLE_WORDS = {"table", "tables", "spreadsheet", "sheet", "row", "rows", "column", "columns", "total", "sum",
                "average", "mean", "highest", "lowest", "largest", "smallest", "maximum", "minimum", "count"}

SQL_PROMPT = """You answer questions with SQLite over the tables below.

{schemas}
{hints}
QUESTION: {query}

Write one to three read-only SQLite SELECT queries that answer the question from these tables:
one query per part of the question (for "which is largest, and what is the total of X?" write two).
Rules:
- Use only the tables and columns listed. Write identifiers in double quotes exactly as listed.
- REAL columns hold plain numbers (no units, commas or % signs); TEXT columns hold text as printed.
- Match text with LIKE '%word%' (case-insensitive) rather than exact equality when names may vary.
- For "largest" or "smallest" use ORDER BY ... DESC/ASC LIMIT 1 over the whole table, without GROUP BY.
- For a category named in the question, match every row that belongs to it, including synonyms and
  abbreviations (solar: '%solar%', '%photovoltaic%', '%PV%'), and return those rows with their values,
  plus the total in its own query, so the reader can see what was counted.
- Return the rows or aggregates that answer each part, with readable column aliases; at most 50 rows.
- If no table can answer the question, return an empty list.
Return JSON only: {{"queries": [{{"table": "<table name>", "sql": "SELECT ...", "answers": "the part of the question it answers"}}]}}"""


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def asks_about_tables(query: str) -> bool:
    """True when the question names tables, rows or columns, or asks for an aggregate."""
    return bool(set(_WORD.findall((query or "").lower())) & _TABLE_WORDS)


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s", "ing", "ed"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _terms(text: str) -> set:
    return {_stem(w) for w in _WORD.findall((text or "").lower()) if len(w) >= 3 and w not in _STOP}


def _format_value(v: Any) -> Any:
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return int(v)
    if isinstance(v, float):
        return round(v, 6)
    return v


class TableQAAgent:
    """Answers questions over document tables with validated SQL."""

    def __init__(self, table_store: TableStore, model_name: str = "qwen2.5:7b-instruct",
                 embed: Optional[Callable[[List[str]], List[List[float]]]] = None):
        self.table_store = table_store
        self.model_name = model_name
        self.embed = embed  # text -> vector, for value hints (optional)

    def value_hints(self, query: str, tables: List[Dict[str, Any]]) -> str:
        """
        Cell values that mean the same as words of the question ("solar" -> "Photovoltaic
        plants", "Rooftop PV systems"), found by embedding similarity, so the SQL matches every
        row of a category and not only rows containing the word itself.
        """
        if self.embed is None:
            return ""
        values: List[str] = []
        for t in tables:
            values.extend(v for v in self.table_store.text_values(t["table"], limit=200) if 2 < len(v) <= 80)
        values = list(dict.fromkeys(values))[:300]
        header = {w for t in tables for c in t["columns"] for w in _terms(c["name"])}
        terms = [w for w in dict.fromkeys(_WORD.findall((query or "").lower()))
                 if len(w) >= 3 and w not in _STOP and w not in _TABLE_WORDS and _stem(w) not in header][:6]
        if not values or not terms:
            return ""
        try:
            vectors = self.embed(terms + values)
        except Exception as e:
            logger.info(f"Value hints skipped ({e}).")
            return ""
        term_vecs, value_vecs = vectors[:len(terms)], vectors[len(terms):]
        lines = []
        for term, tv in zip(terms, term_vecs):
            sims = sorted(((_cosine(tv, vv), v) for v, vv in zip(values, value_vecs)), reverse=True)
            if not sims or sims[0][0] < HINT_MIN_SIMILARITY:
                continue
            cut = max(HINT_MIN_SIMILARITY - 0.05, sims[0][0] - HINT_SPREAD)
            related = [v for sim, v in sims if sim >= cut]
            if len(related) > max(3, len(values) // 2):
                continue  # a word that fits half the table ("energy") does not pick out rows
            related = related[:6]
            if any(term not in v.lower() for v in related):  # only useful when it adds values beyond literal matches
                lines.append(f'- "{term}" may refer to: ' + ", ".join(repr(v) for v in related))
        if not lines:
            return ""
        return "\nVALUES THAT MAY BELONG TO WORDS OF THE QUESTION (use every one that fits, with IN or several LIKEs):\n" + "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ selection
    def candidate_tables(self, query: str, doc_ids: Optional[Sequence[str]]) -> List[Tuple[float, Dict[str, Any]]]:
        tables = self.table_store.tables_for(doc_ids or None)
        if not tables:
            return []
        q_terms = _terms(query)
        asks_for_table = asks_about_tables(query)
        scored = []
        for t in tables:
            header_terms = _terms(t["title"]) | set().union(*[_terms(c["name"]) for c in t["columns"]] or [set()])
            cell_terms = _terms(" ".join(self.table_store.text_values(t["table"], limit=300)))
            score = 2.0 * len(q_terms & header_terms) + 1.0 * len(q_terms & cell_terms) + (1.0 if asks_for_table else 0.0)
            if score > 0:
                scored.append((score, t))
        scored.sort(key=lambda s: s[0], reverse=True)
        return scored[:MAX_TABLES]

    def _schema_block(self, t: Dict[str, Any]) -> str:
        where = f"page {t['page']}" if t.get("page") else "spreadsheet"
        lines = [f'TABLE "{t["table"]}" - {t["title"]} ({where}, {t["n_rows"]} rows)', "Columns:"]
        for c in t["columns"]:
            label = f"  (printed as: {c['name']})" if c["name"].lower() != c["sql"] else ""
            lines.append(f'  "{c["sql"]}" {c["type"]}{label}')
        samples = self.table_store.sample_rows(t["table"], 3)
        if samples:
            lines.append("Sample rows:")
            for row in samples:
                lines.append("  (" + ", ".join(repr(_format_value(v)) for v in row) + ")")
        return "\n".join(lines)

    # ------------------------------------------------------------------ run
    @staticmethod
    def _planned_queries(plan: Any) -> List[Dict[str, Any]]:
        """The queries of the model's plan ({"queries": [...]}, or a single {"sql": ...})."""
        if not isinstance(plan, dict):
            return []
        items = plan.get("queries") if isinstance(plan.get("queries"), list) else [plan]
        return [q for q in items if isinstance(q, dict) and q.get("sql")][:MAX_QUERIES]

    def _result(self, table: Dict[str, Any], query: str, sql: str, result: Dict[str, Any], purpose: str = "") -> Dict[str, Any]:
        labels = {c["sql"]: c["name"] for c in table["columns"]}
        return {
            "table": table["table"],
            "table_id": table["table_id"],
            "title": table["title"],
            "doc_id": table["doc_id"],
            "page": table.get("page"),
            "bbox": table.get("bbox"),
            "question": query,
            "purpose": purpose,
            "sql": sql.strip(),
            "columns": [labels.get(c, c) for c in result["columns"]],
            "rows": [[_format_value(v) for v in r] for r in result["rows"][:50]],
            "row_count": len(result["rows"]),
            "truncated": result["truncated"] or len(result["rows"]) > 50,
        }

    def answer(self, query: str, doc_ids: Optional[Sequence[str]]) -> Tuple[List[Dict[str, Any]], str]:
        """Returns (results, detail) for a question; results is empty when no table applies."""
        candidates = [t for score, t in self.candidate_tables(query, doc_ids) if score >= MIN_SCORE]
        if not candidates:
            return [], "No table matches the question."
        return self.answer_with(query, candidates)

    def answer_with(self, query: str, candidates: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str]:
        """One SQL planning call over the given tables, then the queries are run and checked."""
        allowed = [t["table"] for t in candidates]
        prompt = SQL_PROMPT.format(schemas="\n\n".join(self._schema_block(t) for t in candidates),
                                   hints=self.value_hints(query, candidates), query=query)
        results: List[Dict[str, Any]] = []
        error = ""
        for attempt in range(2):
            try:
                plan = chat_json(self.model_name, prompt + error, num_predict=600)
            except Exception as e:
                return [], f"SQL planning failed: {e}"
            planned = self._planned_queries(plan)
            if not planned:
                break
            failures = []
            for q in planned:
                sql = str(q["sql"])
                try:
                    result = self.table_store.run_select(sql, allowed)
                except ValueError as e:
                    logger.info(f"TableQA query rejected (attempt {attempt + 1}): {e} | {sql}")
                    failures.append(f"Query: {sql}\nError: {e}")
                    continue
                table = self._table_used(sql, candidates, q)
                results.append(self._result(table, query, sql, result, str(q.get("answers") or "")[:160]))
            if results or not failures:
                break
            error = "\n\nYour previous queries failed:\n" + "\n".join(failures) + "\nWrite corrected queries."
        if not results:
            return [], (f"SQL failed twice: {error.strip()[:200]}" if error else "The model found no table that answers the question.")
        # A text search (LIKE) that matched nothing shows little (the rows may use other words),
        # and the writer would cite it as proof that nothing matches: leave it out.
        results = [r for r in results if r["row_count"] or not _TEXT_MATCH.search(r["sql"])]
        if not results:
            return [], "The table queries matched no rows."
        results.extend(self._whole_tables(results, candidates, query))
        used = sorted({r["title"] for r in results})
        rows = sum(r["row_count"] for r in results if r.get("purpose") != "all rows")
        return results, f"{len(results)} result(s), {rows} row(s) from {', '.join(used)}"

    def _whole_tables(self, results: List[Dict[str, Any]], candidates: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """Small tables the queries used, in full, unless a query already returned all of it."""
        extra = []
        for t in candidates:
            mine = [r for r in results if r["table"] == t["table"]]
            if not mine or t["n_rows"] > SMALL_TABLE_ROWS or len(t["columns"]) > SMALL_TABLE_COLUMNS:
                continue
            if any(r["row_count"] >= t["n_rows"] and len(r["columns"]) >= len(t["columns"]) for r in mine):
                continue
            sql = f'SELECT * FROM "{t["table"]}"'
            try:
                result = self.table_store.run_select(sql, [t["table"]], max_rows=SMALL_TABLE_ROWS)
            except ValueError:
                continue
            extra.append(self._result(t, query, sql, result, "all rows"))
        return extra

    @staticmethod
    def _table_used(sql: str, candidates: List[Dict[str, Any]], plan: Any) -> Dict[str, Any]:
        named = str((plan or {}).get("table") or "") if isinstance(plan, dict) else ""
        for t in candidates:
            if t["table"] in sql or t["table"] == named:
                return t
        return candidates[0]

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        started = time.perf_counter()
        semantic = state.get("semantic_query")
        query = getattr(semantic, "resolved_query", None) or state.get("user_query", "")
        query = re.sub(r"\n\n\[Instruction:.*$", "", query, flags=re.S)
        try:
            results, detail = self.answer(query, state.get("document_ids") or None)
        except Exception as e:
            logger.warning(f"TableQA failed: {e}")
            return {"table_results": [], "agent_traces": [trace("table_qa", "failed", str(e)[:200], started)]}
        status = "completed" if results else "skipped"
        return {"table_results": results, "agent_traces": [trace("table_qa", status, detail, started)]}

    def has_tables(self, doc_ids: Optional[Sequence[str]]) -> bool:
        try:
            return bool(self.table_store.tables_for(doc_ids or None))
        except Exception:
            return False


def table_evidence_text(result: Dict[str, Any]) -> str:
    """How a SQL result is shown to the writer and the verifier."""
    where = f" (page {result['page']})" if result.get("page") else ""
    if result.get("purpose") == "all rows":
        lines = [f"All rows of the table '{result['title']}'{where}.",
                 "Columns: " + " | ".join(str(c) for c in result["columns"])]
    else:
        lines = [f"SQL result from the table '{result['title']}'{where}.",
                 f"It answers: {result.get('purpose') or result.get('question', '')}",
                 f"Query: {result['sql']}",
                 "Result columns: " + " | ".join(str(c) for c in result["columns"])]
    rows = result["rows"][:RESULT_ROWS_IN_EVIDENCE]
    if not rows:
        lines.append("The query returned no rows.")
    for r in rows:
        lines.append("- " + " | ".join("" if v is None else str(v) for v in r))
    if result.get("truncated") or len(result["rows"]) > RESULT_ROWS_IN_EVIDENCE:
        lines.append(f"(more rows not shown; {result.get('row_count')} returned)")
    return "\n".join(lines)
