"""
Structured Data Agent for OmniDoc.

Answers questions over everything tabular with one SQL planning call:

* tables extracted from the documents in scope (PDF, Word and spreadsheet tables), picked
  by how well their titles, columns and cell values match the question. Tables of text only
  (a reading list: Book | Author) are left to passage search, which reads them whole, unless
  the question asks about rows, columns or totals: a LIKE filter would only narrow them;
* the library records (``t_library``: one row per document; ``t_records_<type>``: the
  fields extracted from invoices, contracts, receipts, ... after upload) when the question
  is about the collection itself ("how many contracts expire in 2027?", "total due across
  all invoices from Northwind").

Writing, running and checking the SQL is done by the table agent (read-only, sandboxed
SQLite); this agent decides which tables it may use.
"""
import re
import time
import logging
from typing import Any, Dict, List, Optional

from core.state import AgentWorkflowState
from agents.llm_utils import trace
from agents.table_agent import TableQAAgent, MIN_SCORE, asks_about_tables
from retrieval.table_store import LIBRARY_DOC_ID

logger = logging.getLogger("OmniDoc.StructuredDataAgent")

_LIBRARY_RE = re.compile(r"\b(documents?|files?|library|uploads?|invoices?|receipts?|contracts?|resumes?|cvs?|statements?|"
                         r"purchase orders?|reports?|papers?|scanned|pages)\b", re.I)


def _has_numbers(table: Dict[str, Any]) -> bool:
    return any(c.get("type") == "REAL" for c in table.get("columns") or [])


class StructuredDataAgent:
    """Chooses document tables and library records for a question and runs one SQL plan over them."""

    def __init__(self, table_agent: TableQAAgent):
        self.table_agent = table_agent

    def _library_tables(self, query: str, needs: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not (needs.get("library") or (_LIBRARY_RE.search(query) and asks_about_tables(query))):
            return []
        tables = self.table_agent.table_store.tables_for([LIBRARY_DOC_ID])
        words = {w.lower().rstrip("s") for w in re.findall(r"[A-Za-z]+", query)}
        # The overview table always; record tables of the types the question names (or all if none is named).
        named = [t for t in tables if t["table"].startswith("t_records_")
                 and any(w in t["title"].lower() for w in words if len(w) > 3)]
        overview = [t for t in tables if t["table"] == "t_library"]
        return overview + (named or [t for t in tables if t["table"].startswith("t_records_")][:3])

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        started = time.perf_counter()
        needs = state.get("needs") or {}
        semantic_q = state.get("semantic_query")
        query = getattr(semantic_q, "resolved_query", None) or state.get("user_query", "")
        query = re.sub(r"\n\n\[Instruction:.*$", "", query, flags=re.S)
        doc_ids: Optional[List[str]] = state.get("document_ids") or None

        about_tables = asks_about_tables(query)
        candidates = [t for score, t in self.table_agent.candidate_tables(query, doc_ids)
                      if score >= MIN_SCORE and (about_tables or _has_numbers(t))]
        library = self._library_tables(query, needs)
        if not candidates and not library:
            return {}
        try:
            results, detail = self.table_agent.answer_with(query, (library + candidates)[:4])
        except Exception as e:
            logger.warning(f"Structured data query failed: {e}")
            return {"table_results": [], "agent_traces": [trace("structured_data", "failed", str(e)[:200], started)]}
        if library:
            detail += f" (library records: {', '.join(t['title'] for t in library)})"
        return {"table_results": results,
                "agent_traces": [trace("structured_data", "completed" if results else "skipped", detail, started)]}

    def has_data(self, doc_ids: Optional[List[str]], needs: Dict[str, Any]) -> bool:
        return bool(needs.get("library")) or self.table_agent.has_tables(doc_ids)
