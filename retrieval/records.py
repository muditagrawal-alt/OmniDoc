"""
Library records: the documents themselves as SQL tables.

* ``t_library``: one row per document (title, type, pages, scanned pages, tables, upload
  date, size, whether it has a summary and extracted fields);
* ``t_records_<type>``: one row per document of a type (invoices, contracts, receipts, ...)
  with the fields extracted from it after upload and whether its consistency checks pass.

The structured-data agent queries these tables with the same read-only SQL as document
tables, so "how many scanned documents do I have?" or "total due across all invoices from
Northwind" is one query. Extracted records are kept as JSON next to the other document data.
"""
import os
import re
import json
import logging
import threading
from typing import Any, Dict, List, Optional

from retrieval.table_store import TableStore, LIBRARY_DOC_ID

logger = logging.getLogger("OmniDoc.Records")

_SAFE = re.compile(r"^[A-Za-z0-9_\-.]+$")
PLURALS = {"invoice": "invoices", "receipt": "receipts", "purchase_order": "purchase orders", "contract": "contracts",
           "resume": "resumes", "research_paper": "research papers", "bank_statement": "bank statements", "report": "reports"}


class LibraryRecords:
    def __init__(self, table_store: TableStore, records_dir: str):
        self.table_store = table_store
        self.records_dir = records_dir
        os.makedirs(records_dir, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, doc_id: str) -> str:
        return os.path.join(self.records_dir, f"{doc_id}.json")

    def save(self, doc_id: str, record: Dict[str, Any]) -> None:
        if not _SAFE.match(doc_id or ""):
            return
        tmp = self._path(doc_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, self._path(doc_id))

    def load(self, doc_id: str) -> Optional[Dict[str, Any]]:
        if not _SAFE.match(doc_id or ""):
            return None
        try:
            with open(self._path(doc_id), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def delete(self, doc_id: str) -> None:
        if _SAFE.match(doc_id or ""):
            try:
                os.remove(self._path(doc_id))
            except OSError:
                pass

    def all(self) -> Dict[str, Dict[str, Any]]:
        out = {}
        for name in os.listdir(self.records_dir):
            if name.endswith(".json"):
                rec = self.load(name[:-5])
                if rec:
                    out[name[:-5]] = rec
        return out

    def refresh(self, documents: List[Dict[str, Any]]) -> int:
        """
        Rebuilds the record tables from the document list (dicts with id, title, file_type,
        upload_date, size_bytes, pages, ocr_pages, tables, doc_type, has_summary). Returns the
        number of tables written.
        """
        with self._lock:
            records = self.all()
            library_rows = []
            by_type: Dict[str, List[Dict[str, Any]]] = {}
            for d in documents:
                rec = records.get(d["id"]) or {}
                doc_type = rec.get("doc_type") or d.get("doc_type") or "other"
                checks = rec.get("validation") or []
                failed = [c for c in checks if c.get("status") == "fail"]
                library_rows.append([
                    d.get("title") or d["id"], doc_type.replace("_", " "), d.get("pages") or None, d.get("ocr_pages") or 0,
                    d.get("tables") or 0, str(d.get("upload_date") or "")[:10] or None,
                    round((d.get("size_bytes") or 0) / 1024, 1), "yes" if d.get("has_summary") else "no",
                    "yes" if rec.get("fields") else "no", f"{len(failed)} failed" if failed else ("ok" if checks else None),
                ])
                if rec.get("fields"):
                    by_type.setdefault(doc_type, []).append({"title": d.get("title") or d["id"], "record": rec})
            written = 0
            if self.table_store.put_table("t_library", LIBRARY_DOC_ID, {
                "title": "Library: all documents", "source": "library",
                "columns": ["Document", "Type", "Pages", "Scanned pages", "Tables", "Uploaded", "Size KB", "Has summary",
                            "Has extracted fields", "Checks"],
                "rows": library_rows,
            }):
                written += 1
            existing = {t["table"] for t in self.table_store.tables_for([LIBRARY_DOC_ID]) if t["table"].startswith("t_records_")}
            current = set()
            for doc_type, items in by_type.items():
                name = "t_records_" + re.sub(r"[^0-9a-z]+", "_", doc_type.lower()).strip("_")
                current.add(name)
                labels = []
                for it in items:
                    for f in it["record"]["fields"]:
                        if f["label"] not in labels:
                            labels.append(f["label"])
                rows = []
                for it in items:
                    values = {f["label"]: _cell(f) for f in it["record"]["fields"]}
                    checks = it["record"].get("validation") or []
                    failed = [c["rule"] for c in checks if c.get("status") == "fail"]
                    rows.append([it["title"]] + [values.get(label) for label in labels] +
                                ["; ".join(failed) if failed else ("ok" if checks else None)])
                if self.table_store.put_table(name, LIBRARY_DOC_ID, {
                    "title": f"Library records: {PLURALS.get(doc_type, doc_type.replace('_', ' ') + 's')}", "source": "records",
                    "columns": ["Document"] + labels + ["Failed checks"], "rows": rows,
                }):
                    written += 1
            for stale in existing - current:
                self.table_store.put_table(stale, LIBRARY_DOC_ID, {"rows": []})
            return written


def _cell(field: Dict[str, Any]) -> Any:
    value = field.get("value")
    if value is None or field.get("status") == "missing":
        return None
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return value
