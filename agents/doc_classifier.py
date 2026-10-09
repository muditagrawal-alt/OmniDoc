"""
Document type detection at upload, without a model call.

Weighted cue phrases over the first pages, the file name and the file type decide among
invoice, receipt, purchase order, contract, resume, research paper, bank statement, report,
letter, presentation, spreadsheet and form. A document needs a clear margin over the
runner-up; otherwise it is "other". The type selects the extraction template that runs in
the background after upload and the record table the document is listed in.
"""
import re
from typing import Any, Dict, List, Sequence, Tuple

# (pattern, weight). Patterns are matched case-insensitively against the opening text.
CUES: Dict[str, List[Tuple[str, float]]] = {
    "invoice": [(r"\btax invoice\b", 4), (r"\binvoice\b", 2.5), (r"\binvoice (no|number|#|date)\b", 3), (r"\bbill to\b", 2),
                (r"\b(gstin|vat (no|number)|hsn|sac code)\b", 2), (r"\b(amount|total|balance) due\b", 2), (r"\bsubtotal\b", 1.5),
                (r"\bdue date\b", 1.5), (r"\bunit price\b", 1), (r"\bpayment terms\b", 1)],
    "receipt": [(r"\breceipt\b", 3), (r"\b(cash|card|upi|change)\b.{0,20}\b(paid|tendered|received)\b", 2),
                (r"\bthank you for (shopping|your purchase|visiting)\b", 2.5), (r"\b(cashier|till|store #|terminal)\b", 1.5),
                (r"\b(qty|item)\b.{0,40}\b(price|amt)\b", 1)],
    "purchase_order": [(r"\bpurchase order\b", 4), (r"\bp\.?o\.? (no|number|#)\b", 3), (r"\bship to\b", 1.5), (r"\bvendor\b", 1)],
    "contract": [(r"\b(agreement|contract)\b", 2), (r"\b(this agreement|the parties|hereinafter|hereto|whereas|witnesseth)\b", 2.5),
                 (r"\b(governing law|jurisdiction|indemnif|termination|confidentiality|force majeure)\b", 2),
                 (r"\b(effective date|term of (this|the) agreement)\b", 2), (r"\bin witness whereof\b", 3), (r"\bclause \d", 1)],
    "resume": [(r"\b(curriculum vitae|resume|résumé)\b", 3), (r"\b(work experience|professional experience|employment history)\b", 3),
               (r"\b(education|skills|certifications|projects)\b", 1), (r"\b(linkedin\.com|github\.com)\b", 2),
               (r"\b(objective|career summary|profile summary)\b", 1.5)],
    "research_paper": [(r"\babstract\b", 2.5), (r"\b(introduction|related work|methodology|conclusion)s?\b", 1.5),
                       (r"\breferences\b", 1.5), (r"\bet al\.", 2), (r"\b(arxiv|doi:|proceedings|journal of)\b", 2),
                       (r"\b(we propose|in this paper|our results|state[- ]of[- ]the[- ]art)\b", 2), (r"\[\d+(,\s*\d+)*\]", 1)],
    "bank_statement": [(r"\b(bank )?statement of account\b", 4), (r"\baccount statement\b", 3), (r"\b(opening|closing) balance\b", 3),
                       (r"\b(ifsc|account (no|number)|a/c no)\b", 2), (r"\b(withdrawal|deposit|debit|credit)s?\b", 1),
                       (r"\btransaction (date|details)\b", 2)],
    "report": [(r"\b(annual|quarterly|progress|status|audit|technical|research) report\b", 3), (r"\bexecutive summary\b", 3),
               (r"\b(findings|recommendations)\b", 1.5), (r"\btable of contents\b", 1.5), (r"\b(fiscal year|fy\s?\d{2})\b", 1)],
    "letter": [(r"^\s*dear\b", 3), (r"\b(yours (sincerely|faithfully|truly)|sincerely|regards)\b", 2.5),
               (r"\bsubject\s*:", 1.5), (r"\b(ref(erence)?\s*(no|:))", 1)],
    "form": [(r"\b(application form|registration form|form no)\b", 3), (r"\b(signature of|date of birth|applicant)\b", 2),
             (r"\b(tick|check) (the )?(box|appropriate)\b", 2), (r"_{6,}", 1.5)],
}
BY_EXTENSION = {"pptx": ("presentation", 5.0), "csv": ("spreadsheet", 5.0), "tsv": ("spreadsheet", 5.0),
                "xlsx": ("spreadsheet", 5.0), "eml": ("email", 6.0), "epub": ("book", 5.0)}
LABELS = {
    "invoice": "Invoice", "receipt": "Receipt", "purchase_order": "Purchase order", "contract": "Contract", "resume": "Resume",
    "research_paper": "Research paper", "bank_statement": "Bank statement", "report": "Report", "letter": "Letter",
    "form": "Form", "presentation": "Presentation", "spreadsheet": "Spreadsheet", "email": "Email", "book": "Book",
    "audio": "Recording", "web_page": "Web page", "other": "Document",
}


def classify(text: str, filename: str = "", file_type: str = "", extra: Sequence[str] = ()) -> Dict[str, Any]:
    """{"type", "label", "confidence", "scores"} for a document's opening text."""
    ext = (file_type or filename.rsplit(".", 1)[-1] if "." in filename else file_type or "").lower()
    if ext in ("mp3", "wav", "m4a", "ogg", "webm", "mp4", "mov", "flac", "mpeg", "mpga"):
        return {"type": "audio", "label": LABELS["audio"], "confidence": 1.0, "scores": {}}
    sample = (text or "")[:6000]
    name = re.sub(r"[_\-.]+", " ", filename or "").lower()
    scores: Dict[str, float] = {}
    for kind, cues in CUES.items():
        total = 0.0
        for pattern, weight in cues:
            hits = len(re.findall(pattern, sample, re.I | re.M))
            total += weight * min(hits, 3) ** 0.5
            if re.search(pattern, name, re.I):
                total += weight
        scores[kind] = round(total, 2)
    if ext in BY_EXTENSION:
        kind, bonus = BY_EXTENSION[ext]
        scores[kind] = scores.get(kind, 0.0) + bonus
    for tag in extra:
        scores[tag] = scores.get(tag, 0.0) + 3.0
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_score < 4.0 or best_score < runner * 1.25:
        best = "other"
    confidence = 0.0 if best == "other" else round(min(1.0, best_score / 12.0) * (1 - runner / max(best_score, 1e-6) * 0.5), 2)
    return {"type": best, "label": LABELS.get(best, best.title()), "confidence": confidence,
            "scores": {k: v for k, v in ranked[:4] if v > 0}}
