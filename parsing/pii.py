"""
Sensitive data: finding it and redacting it.

Detectors are patterns with checks that cut false alarms: Aadhaar numbers must pass the
Verhoeff checksum, card numbers the Luhn check, IBANs the mod-97 check; account, passport
and voter-ID numbers and dates of birth need a nearby keyword. Each finding is located on
its page (PDF text layer or OCR words), so the viewer can highlight it, and a redacted copy
replaces it: PDFs and scans get real redactions (the text and image pixels under each box
are removed, metadata scrubbed), text documents get the values blacked out.
"""
import re
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("OmniDoc.PII")

# Verhoeff tables (Aadhaar checksum)
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def luhn_ok(number: str) -> bool:
    total, alt = 0, False
    for ch in reversed(number):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def iban_ok(value: str) -> bool:
    v = value.replace(" ", "").upper()
    rearranged = v[4:] + v[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _near(text: str, start: int, pattern: str, window: int = 40) -> bool:
    return bool(re.search(pattern, text[max(0, start - window):start], re.I))


# (type, label, regex, check(match_text, full_text, start) -> bool)
Detector = Tuple[str, str, re.Pattern, Callable[[str, str, int], bool]]
DETECTORS: List[Detector] = [
    ("aadhaar", "Aadhaar number", re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)"),
     lambda m, t, s: verhoeff_ok(_digits(m))),
    ("pan", "PAN", re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b"), lambda m, t, s: True),
    ("gstin", "GSTIN", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"), lambda m, t, s: True),
    ("ifsc", "IFSC code", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), lambda m, t, s: True),
    ("card", "Card number", re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
     lambda m, t, s: 13 <= len(_digits(m)) <= 19 and luhn_ok(_digits(m)) and not _near(t, s, r"account|a/c|acct|phone|mobile|tel", 25)),
    ("iban", "IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"), lambda m, t, s: iban_ok(m)),
    ("account", "Bank account number", re.compile(r"(?<![\d-])\d{9,18}(?![\d-])"),
     lambda m, t, s: _near(t, s, r"(account|a/c|acct|ac)\s*(no|number|#)?\.?\s*[:\-]?\s*$", 30)),
    ("passport", "Passport number", re.compile(r"\b[A-PR-WY][1-9]\d ?\d{4}[1-9]\b"), lambda m, t, s: _near(t, s, r"passport", 50)),
    ("voter_id", "Voter ID", re.compile(r"\b[A-Z]{3}\d{7}\b"), lambda m, t, s: _near(t, s, r"voter|epic|election", 50)),
    ("ssn", "US social security number", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), lambda m, t, s: True),
    ("phone", "Phone number", re.compile(r"(?<![\w+])(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)|\+\d{1,3}[ -]?\(?\d{2,4}\)?[ -]?\d{3,4}[ -]?\d{3,4}(?!\d)"),
     lambda m, t, s: 10 <= len(_digits(m)) <= 15),
    ("email", "Email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), lambda m, t, s: True),
    ("dob", "Date of birth", re.compile(r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+(?:19|20)\d{2})\b"),
     lambda m, t, s: _near(t, s, r"(d\.?o\.?b|date of birth|born|birth date)\s*[:\-]?\s*$", 30)),
]
LABELS = {t: label for t, label, _, _ in DETECTORS}


def mask(kind: str, value: str) -> str:
    """Shows enough to recognise a value without revealing it."""
    v = value.strip()
    if kind == "email":
        name, _, domain = v.partition("@")
        return (name[:1] + "•" * max(1, len(name) - 1)) + "@" + domain
    digits = re.sub(r"[^A-Za-z0-9]", "", v)
    if len(digits) <= 4:
        return "•" * len(digits)
    return "•" * (len(digits) - 4) + digits[-4:]


def find_in_text(text: str, kinds: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Findings in a text: {type, label, start, end, value, masked}; overlapping matches keep the first detector's."""
    wanted = set(kinds) if kinds else None
    found: List[Dict[str, Any]] = []
    taken: List[Tuple[int, int]] = []
    for kind, label, pattern, check in DETECTORS:
        if wanted is not None and kind not in wanted:
            continue
        for m in pattern.finditer(text):
            start, end = m.span()
            if any(a < end and start < b for a, b in taken):
                continue
            try:
                ok = check(m.group(0), text, start)
            except (ValueError, IndexError):
                ok = False
            if ok:
                taken.append((start, end))
                found.append({"type": kind, "label": label, "start": start, "end": end, "value": m.group(0),
                              "masked": mask(kind, m.group(0))})
    found.sort(key=lambda f: f["start"])
    return found


def _page_text(words: Sequence[Sequence[Any]]) -> Tuple[str, List[Tuple[int, int, int]]]:
    """Page words joined with spaces, and (start, end, word index) of each word in that text."""
    parts, spans, pos = [], [], 0
    for i, w in enumerate(words):
        token = str(w[4])
        parts.append(token)
        spans.append((pos, pos + len(token), i))
        pos += len(token) + 1
    return " ".join(parts), spans


def find_on_page(doc: Any, page_no: int, layout: Dict[str, Any], kinds: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Findings on one page with their boxes in page points (``boxes``) and normalised (``rects``)."""
    from parsing.locate import page_words, _line_rects
    words = page_words(doc, page_no, layout)
    text, spans = _page_text(words)
    page = doc[page_no - 1]
    width, height = float(page.rect.width) or 1.0, float(page.rect.height) or 1.0
    out = []
    for f in find_in_text(text, kinds):
        idx = [i for a, b, i in spans if a < f["end"] and f["start"] < b]
        boxes = _line_rects([words[i][:4] for i in idx])
        if not boxes:
            continue
        context = text[max(0, f["start"] - 50):f["end"] + 50]
        out.append({**f, "page": page_no, "boxes": boxes,
                    "rects": [[round(x0 / width, 5), round(y0 / height, 5), round(x1 / width, 5), round(y1 / height, 5)]
                              for x0, y0, x1, y1 in boxes],
                    "context": context.replace(f["value"], f["masked"])})
    return out


def find_in_document(doc: Any, layout: Dict[str, Any], kinds: Optional[Iterable[str]] = None, max_pages: int = 500) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for page_no in range(1, min(len(doc), max_pages) + 1):
        findings.extend(find_on_page(doc, page_no, layout, kinds))
    return findings


def redact_pdf(doc: Any, findings: List[Dict[str, Any]]) -> bytes:
    """Applies real redactions (text and image pixels removed) over the findings; returns the new PDF."""
    import fitz
    by_page: Dict[int, List[List[float]]] = {}
    for f in findings:
        by_page.setdefault(f["page"], []).extend(f["boxes"])
    for page_no, boxes in by_page.items():
        page = doc[page_no - 1]
        for x0, y0, x1, y1 in boxes:
            page.add_redact_annot(fitz.Rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1), fill=(0, 0, 0))
        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        except TypeError:  # older PyMuPDF
            page.apply_redactions()
    doc.set_metadata({})
    try:
        doc.scrub()
    except Exception:
        pass
    return doc.tobytes(garbage=4, deflate=True)


def redact_text(text: str, kinds: Optional[Iterable[str]] = None) -> Tuple[str, int]:
    """The text with every finding replaced by █ characters; returns (text, number replaced)."""
    findings = find_in_text(text, kinds)
    out, pos = [], 0
    for f in findings:
        out.append(text[pos:f["start"]])
        out.append("█" * len(f["value"]))
        pos = f["end"]
    out.append(text[pos:])
    return "".join(out), len(findings)
