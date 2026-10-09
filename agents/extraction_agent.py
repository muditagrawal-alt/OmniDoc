"""
Schema extraction: fill a form (invoice, contract, paper, report or your own fields) from a
document, with a citation and a verbatim quote for every value.

For each field the agent retrieves the passages most likely to state it, the local model
returns a value, the number of the passage it came from and the exact words that state it,
and every answer is checked: the quote must occur in that passage (or the citation is moved
to the passage that does contain it) and the value must occur in the quote. Values that
fail the check are kept but marked for review, never presented as verified.
"""
import re
import json
import time
import logging
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from agents.llm_utils import chat_json, number_in_text, to_number
from agents.citations import public_sources, _new_source, format_evidence_block

logger = logging.getLogger("OmniDoc.ExtractionAgent")

FIELDS_PER_CALL = 10
PASSAGES_PER_FIELD = 4
MAX_PASSAGES = 14
FIELD_TYPES = ("text", "number", "date", "list", "boolean")

PRESETS: Dict[str, Dict[str, Any]] = {
    "invoice": {
        "label": "Invoice",
        "description": "Invoices and bills",
        "fields": [
            {"name": "invoice_number", "label": "Invoice number", "description": "The invoice number or ID", "type": "text"},
            {"name": "invoice_date", "label": "Invoice date", "description": "Date the invoice was issued", "type": "date"},
            {"name": "due_date", "label": "Due date", "description": "Date payment is due", "type": "date"},
            {"name": "vendor", "label": "Vendor", "description": "Company or person issuing the invoice", "type": "text"},
            {"name": "customer", "label": "Bill to", "description": "Company or person being billed", "type": "text"},
            {"name": "subtotal", "label": "Subtotal", "description": "Amount before tax", "type": "number"},
            {"name": "tax", "label": "Tax", "description": "Total tax amount (GST, VAT or sales tax)", "type": "number"},
            {"name": "total", "label": "Total due", "description": "Total amount due including tax", "type": "number"},
            {"name": "currency", "label": "Currency", "description": "Currency of the amounts", "type": "text"},
        ],
    },
    "contract": {
        "label": "Contract",
        "description": "Agreements and contracts",
        "fields": [
            {"name": "parties", "label": "Parties", "description": "The parties to the agreement", "type": "list"},
            {"name": "effective_date", "label": "Effective date", "description": "Date the agreement takes effect", "type": "date"},
            {"name": "term", "label": "Term", "description": "Duration of the agreement", "type": "text"},
            {"name": "end_date", "label": "End date", "description": "Date the agreement ends or expires", "type": "date"},
            {"name": "payment_terms", "label": "Payment terms", "description": "Fees and when they are paid", "type": "text"},
            {"name": "termination", "label": "Termination", "description": "How and with what notice the agreement can be ended", "type": "text"},
            {"name": "renewal", "label": "Renewal", "description": "Whether and how the agreement renews", "type": "text"},
            {"name": "governing_law", "label": "Governing law", "description": "Law or jurisdiction that governs the agreement", "type": "text"},
            {"name": "confidentiality", "label": "Confidentiality", "description": "Confidentiality obligations", "type": "text"},
        ],
    },
    "receipt": {
        "label": "Receipt",
        "description": "Shop and payment receipts",
        "fields": [
            {"name": "merchant", "label": "Merchant", "description": "Shop or business that issued the receipt", "type": "text"},
            {"name": "date", "label": "Date", "description": "Date of the purchase", "type": "date"},
            {"name": "subtotal", "label": "Subtotal", "description": "Amount before tax", "type": "number"},
            {"name": "tax", "label": "Tax", "description": "Tax amount", "type": "number"},
            {"name": "total", "label": "Total", "description": "Total amount paid", "type": "number"},
            {"name": "payment_method", "label": "Paid with", "description": "Cash, card, UPI or other payment method", "type": "text"},
        ],
    },
    "purchase_order": {
        "label": "Purchase order",
        "description": "Purchase orders",
        "fields": [
            {"name": "po_number", "label": "PO number", "description": "The purchase order number", "type": "text"},
            {"name": "order_date", "label": "Order date", "description": "Date of the order", "type": "date"},
            {"name": "delivery_date", "label": "Delivery date", "description": "Requested delivery date", "type": "date"},
            {"name": "buyer", "label": "Buyer", "description": "Company placing the order", "type": "text"},
            {"name": "supplier", "label": "Supplier", "description": "Company supplying the goods", "type": "text"},
            {"name": "total", "label": "Total", "description": "Total order value", "type": "number"},
        ],
    },
    "resume": {
        "label": "Resume",
        "description": "Resumes and CVs",
        "fields": [
            {"name": "name", "label": "Name", "description": "Full name of the candidate", "type": "text"},
            {"name": "email", "label": "Email", "description": "Email address", "type": "text"},
            {"name": "phone", "label": "Phone", "description": "Phone number", "type": "text"},
            {"name": "current_role", "label": "Current role", "description": "Most recent job title and employer", "type": "text"},
            {"name": "years_experience", "label": "Years of experience", "description": "Total years of work experience", "type": "number"},
            {"name": "skills", "label": "Skills", "description": "Main skills", "type": "list"},
            {"name": "education", "label": "Education", "description": "Degrees and institutions", "type": "list"},
        ],
    },
    "bank_statement": {
        "label": "Bank statement",
        "description": "Bank account statements",
        "fields": [
            {"name": "bank", "label": "Bank", "description": "Name of the bank", "type": "text"},
            {"name": "account_holder", "label": "Account holder", "description": "Name of the account holder", "type": "text"},
            {"name": "account_number", "label": "Account number", "description": "Account number (as printed, possibly masked)", "type": "text"},
            {"name": "period_start", "label": "Period from", "description": "First date of the statement period", "type": "date"},
            {"name": "period_end", "label": "Period to", "description": "Last date of the statement period", "type": "date"},
            {"name": "opening_balance", "label": "Opening balance", "description": "Balance at the start of the period", "type": "number"},
            {"name": "total_credits", "label": "Total credits", "description": "Sum of deposits / credits in the period", "type": "number"},
            {"name": "total_debits", "label": "Total debits", "description": "Sum of withdrawals / debits in the period", "type": "number"},
            {"name": "closing_balance", "label": "Closing balance", "description": "Balance at the end of the period", "type": "number"},
        ],
    },
    "paper": {
        "label": "Research paper",
        "description": "Papers and articles",
        "fields": [
            {"name": "title", "label": "Title", "description": "Title of the paper or article", "type": "text"},
            {"name": "authors", "label": "Authors", "description": "Names of the authors", "type": "list"},
            {"name": "problem", "label": "Problem", "description": "The question or problem the work addresses", "type": "text"},
            {"name": "method", "label": "Method", "description": "The approach or method proposed", "type": "text"},
            {"name": "data", "label": "Data", "description": "Datasets, samples or sources used", "type": "list"},
            {"name": "main_result", "label": "Main result", "description": "The headline finding, with its numbers", "type": "text"},
            {"name": "limitations", "label": "Limitations", "description": "Limitations or obstacles the authors state", "type": "text"},
        ],
    },
    "report": {
        "label": "Report",
        "description": "Reports, reviews and audits",
        "fields": [
            {"name": "title", "label": "Title", "description": "Title of the report", "type": "text"},
            {"name": "organisation", "label": "Organisation", "description": "Organisation that prepared or commissioned it", "type": "text"},
            {"name": "date", "label": "Date", "description": "Date of the report", "type": "date"},
            {"name": "purpose", "label": "Purpose", "description": "What the report sets out to do", "type": "text"},
            {"name": "key_findings", "label": "Key findings", "description": "The main findings", "type": "list"},
            {"name": "recommendations", "label": "Recommendations", "description": "Recommended actions", "type": "list"},
        ],
    },
}

EXTRACT_PROMPT = """Extract the requested fields from the NUMBERED PASSAGES of the document "{title}".

FIELDS:
{fields}

NUMBERED PASSAGES:
{passages}

Rules:
- Use only the passages. For each field give "value", "source" (the number of the passage that states it) and "quote" (the exact words from that passage that state the value, copied verbatim, at most 30 words).
- If a field is not stated in the passages, set "value", "source" and "quote" to null. Never guess.
- number fields: digits only, no currency symbols or thousands separators. date fields: as printed. list fields: a JSON array of strings. boolean fields: true or false.
Return JSON only: {{"fields": [{{"name": "...", "value": ..., "source": 1, "quote": "..."}}]}}"""

_TOKEN = re.compile(r"[\w.%/-]+", re.UNICODE)


def _norm_tokens(text: str) -> List[str]:
    return [t.strip(".").lower() for t in _TOKEN.findall(text or "") if t.strip(".")]


def quote_in_text(quote: str, text: str) -> bool:
    """True if the quote occurs in the text (ignoring case, spacing and punctuation)."""
    q, t = _norm_tokens(quote), _norm_tokens(text)
    if not q or not t:
        return False
    if " ".join(q) in " ".join(t):
        return True
    match = SequenceMatcher(None, t, q, autojunk=False).find_longest_match(0, len(t), 0, len(q))
    if match.size >= 0.8 * len(q):
        return True
    # Tolerate small OCR or hyphenation differences, but only around a real contiguous match.
    present = set(t)
    return len(q) >= 4 and match.size >= 0.5 * len(q) and sum(w in present for w in q) >= 0.9 * len(q)


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def dates_in(text: str) -> Set[Tuple[int, int, int]]:
    """
    (year, month, day) of the dates in a text: 2026-08-12, 12/08/2026 (read both ways),
    12 August 2026 and August 12, 2026. Lets "2026-08-12" match "12 August 2026".
    """
    out: Set[Tuple[int, int, int]] = set()
    for y, m, d in re.findall(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", text):
        out.add((int(y), int(m), int(d)))
    for a, b, y in re.findall(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", text):
        out.update({(int(y), int(b), int(a)), (int(y), int(a), int(b))})
    for d, mon, y in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b", text):
        if mon[:3].lower() in _MONTHS:
            out.add((int(y), _MONTHS[mon[:3].lower()], int(d)))
    for mon, d, y in re.findall(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text):
        if mon[:3].lower() in _MONTHS:
            out.add((int(y), _MONTHS[mon[:3].lower()], int(d)))
    return out


def value_in_text(value: Any, ftype: str, text: str) -> bool:
    if value is None or not text:
        return False
    if ftype == "date" and dates_in(str(value)) & dates_in(text):
        return True
    if ftype == "list" and isinstance(value, list):
        items = [v for v in value if str(v).strip()]
        return bool(items) and sum(value_in_text(v, "text", text) for v in items) >= max(1, len(items) // 2 + len(items) % 2)
    if ftype == "boolean":
        return True  # judged from the quote by the model; the quote itself is checked
    if ftype == "number":
        num = to_number(value)
        return num is not None and number_in_text(num, text)
    v_tokens = [t for t in _norm_tokens(str(value)) if len(t) > 1]
    if not v_tokens:
        return False
    t_tokens = set(_norm_tokens(text))
    return sum(t in t_tokens for t in v_tokens) >= 0.6 * len(v_tokens)


def normalise_fields(fields: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validates user-defined fields: name, label, description, type."""
    out, seen = [], set()
    for f in fields[:30]:
        label = str(f.get("label") or f.get("name") or "").strip()[:80]
        name = re.sub(r"[^0-9a-z]+", "_", str(f.get("name") or label).strip().lower()).strip("_")[:60]
        if not name or name in seen:
            continue
        seen.add(name)
        ftype = str(f.get("type") or "text").lower()
        out.append({
            "name": name,
            "label": label or name.replace("_", " ").capitalize(),
            "description": str(f.get("description") or "").strip()[:300],
            "type": ftype if ftype in FIELD_TYPES else "text",
        })
    return out


def _with_heading(chunk: Any) -> str:
    """
    A passage with its section heading, which the parser keeps apart from the text. The
    heading is often the answer: an invoice's company name, a contract's title.
    """
    heading = (chunk.section_title or "").strip()
    text = chunk.text or ""
    if heading and heading.lower() != "general" and heading.lower() not in text.lower():
        return f"{heading}\n{text}"
    return text


class SchemaExtractionAgent:
    """Fills a list of fields from one document, with a checked citation per value."""

    def __init__(self, hybrid_agent: Any, lance_store: Any, model_name: str = "qwen2.5:7b-instruct"):
        self.hybrid_agent = hybrid_agent
        self.lance_store = lance_store
        self.model_name = model_name

    def _passages(self, doc_id: str, fields: List[Dict[str, Any]]) -> List[Any]:
        """Best passages per field, plus the opening of the document (titles, parties, headers)."""
        chosen: Dict[str, Any] = {}
        try:
            opening = self.lance_store.get_document_chunks(doc_id)[:2]
        except Exception:
            opening = []
        for c in opening:
            chosen.setdefault(c.chunk_id, c)
        for f in fields:
            query = f"{f['label']}: {f['description']}" if f["description"] else f["label"]
            hits, _ = self.hybrid_agent.search([query], [doc_id], top_k=PASSAGES_PER_FIELD)
            for h in hits:
                chosen.setdefault(h.chunk_id, h)
            if len(chosen) >= MAX_PASSAGES:
                break
        ordered = list(chosen.values())[:MAX_PASSAGES]
        ordered.sort(key=lambda c: (int(c.page_number or 1), c.chunk_id))
        return ordered

    def extract(self, doc_id: str, title: str, fields: List[Dict[str, Any]],
                progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
        started = time.perf_counter()
        passages = self._passages(doc_id, fields)
        sources = [_new_source("chunk", _with_heading(c), doc_id=doc_id, chunk_id=c.chunk_id, page=int(c.page_number or 1),
                               section=c.section_title or "", title=c.section_title or f"Page {c.page_number}")
                   for c in passages]
        for i, s in enumerate(sources, 1):
            s["n"] = i
        results: Dict[str, Dict[str, Any]] = {}
        batches = [fields[i:i + FIELDS_PER_CALL] for i in range(0, len(fields), FIELDS_PER_CALL)]
        for b, batch in enumerate(batches, 1):
            listing = "\n".join(f"- {f['name']} ({f['type']}): {f['description'] or f['label']}" for f in batch)
            try:
                parsed = chat_json(self.model_name, EXTRACT_PROMPT.format(
                    title=title, fields=listing, passages=format_evidence_block(sources)[:16000]), num_predict=900)
            except Exception as e:
                logger.warning(f"Extraction call failed for {doc_id}: {e}")
                parsed = {}
            answers = {str(a.get("name") or "").strip(): a for a in (parsed.get("fields") or [] if isinstance(parsed, dict) else [])
                       if isinstance(a, dict)}
            for f in batch:
                results[f["name"]] = self._check(f, answers.get(f["name"]) or {}, sources)
            if progress:
                progress(b, len(batches))
        return {
            "doc_id": doc_id,
            "title": title,
            "fields": [results[f["name"]] for f in fields],
            "sources": public_sources(sources),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    @staticmethod
    def _check(field: Dict[str, Any], answer: Dict[str, Any], sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        value = answer.get("value")
        if isinstance(value, str) and value.strip().lower() in ("", "null", "none", "n/a", "not stated", "unknown"):
            value = None
        if field["type"] == "list" and isinstance(value, str):
            value = [v.strip() for v in re.split(r";|\n|, (?=[A-Z])", value) if v.strip()]
        if field["type"] == "number" and value is not None and to_number(value) is not None:
            value = to_number(value)
        quote = str(answer.get("quote") or "").strip()
        try:
            n = int(answer.get("source")) if answer.get("source") is not None else None
        except (TypeError, ValueError):
            n = None
        out = {**field, "value": value, "quote": quote or None, "source": None, "status": "missing",
               "page": None, "chunk_id": None, "note": ""}
        if value is None or value == [] or value == "":
            out["value"] = None
            return out

        by_n = {s["n"]: s for s in sources}
        cited = by_n.get(n)
        # The quote decides which passage really states the value.
        holder = cited if cited and quote and quote_in_text(quote, cited["_text"]) else None
        if holder is None and quote:
            holder = next((s for s in sources if quote_in_text(quote, s["_text"])), None)
            if holder is not None and cited is not None and holder is not cited:
                out["note"] = f"Citation moved from [{n}] to [{holder['n']}], where the quote appears."
        if holder is None:
            holder = cited
        if holder is not None:
            out.update(source=holder["n"], page=holder.get("page"), chunk_id=holder.get("chunk_id") or None)
        quote_ok = bool(quote) and holder is not None and quote_in_text(quote, holder["_text"])
        value_ok = holder is not None and value_in_text(value, field["type"], quote if quote_ok else holder["_text"])
        if quote_ok and value_ok:
            out["status"] = "found"
        else:
            out["status"] = "check"
            out["note"] = out["note"] or ("The quote was not found in the cited passage." if not quote_ok
                                          else "The value does not appear in the quoted text.")
        return out


def results_to_csv_rows(results: List[Dict[str, Any]]) -> List[List[str]]:
    """Header + one row per document with the value of each field."""
    if not results:
        return []
    fields = results[0]["fields"]
    header = ["document"] + [f["label"] for f in fields]
    rows = [header]
    for r in results:
        row = [r["title"]]
        for f in r["fields"]:
            v = f["value"]
            row.append("; ".join(map(str, v)) if isinstance(v, list) else ("" if v is None else str(v)))
        rows.append(row)
    return rows


# Document type (agents/doc_classifier.py) -> extraction template run automatically after upload.
TYPE_PRESETS = {"invoice": "invoice", "receipt": "receipt", "purchase_order": "purchase_order", "contract": "contract",
                "resume": "resume", "research_paper": "paper", "report": "report", "bank_statement": "bank_statement"}


def presets_payload() -> List[Dict[str, Any]]:
    return [{"key": k, "label": v["label"], "description": v["description"], "fields": v["fields"]}
            for k, v in PRESETS.items()]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
