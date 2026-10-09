"""
Finds where a cited passage, or the exact sentence that supports a claim, sits on its page,
so the document viewer can highlight it.

The sentence of the cited passage that best supports the claim (shared words and figures)
is aligned with the words of the page: the PDF's own text layer, or the OCR word boxes for
scanned pages. Matched words are merged into one rectangle per line. Rectangles are
returned normalised to the page size (0..1), so the viewer can draw them over a page image
of any resolution.
"""
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple

_TOKEN = re.compile(r"\w+", re.UNICODE)
# A sentence ends at . ! or ?, optionally followed by a closing bracket or quote ("... successful.) Wind"),
# but not after an initial or an abbreviation such as "U.S." ("according to the U.S. Energy ...").
_SENTENCE = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][)\]\"'”’]))(?<!\b[A-Z]\.)(?<!Pvt\.)(?<!Ltd\.)(?<!Inc\.)(?<!Co\.)"
                       r"(?<!Mr\.)(?<!Dr\.)(?<!No\.)(?<!vs\.)\s+(?=[A-Z0-9\"'(\[“‘])")
_STOP = {"the", "and", "of", "to", "in", "a", "an", "is", "are", "was", "were", "for", "on", "by", "with", "that",
         "this", "it", "its", "as", "at", "from", "be", "or", "which", "would", "will", "can", "about"}


def norm_tokens(text: str) -> List[str]:
    text = unicodedata.normalize("NFKD", text or "").lower()
    return _TOKEN.findall(text)


def best_sentence(passage: str, claim: str) -> str:
    """
    The sentence (or two adjacent sentences) of the passage that best supports the claim;
    empty when no sentence shares a word or figure with it.
    """
    sentences = [s.strip() for s in _SENTENCE.split(passage or "") if s.strip()]
    if not sentences:
        return passage or ""
    claim_tokens = set(norm_tokens(claim)) - _STOP
    claim_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", (claim or "").replace(",", "")))
    if not claim_tokens and not claim_numbers:
        return sentences[0]

    def score(text: str) -> float:
        tokens = set(norm_tokens(text)) - _STOP
        numbers = set(re.findall(r"\d+(?:[.,]\d+)?", text.replace(",", "")))
        return len(tokens & claim_tokens) + 2.0 * len(numbers & claim_numbers)

    best_i = max(range(len(sentences)), key=lambda i: score(sentences[i]))
    if score(sentences[best_i]) == 0:
        return ""  # nothing in common: highlight the whole passage rather than a guess
    best = sentences[best_i]
    # A short best sentence often continues in the next one ("... 3.8 million turbines. Each ...").
    if len(norm_tokens(best)) < 12 and best_i + 1 < len(sentences):
        nxt = sentences[best_i + 1]
        if score(nxt) > 0:
            best = best + " " + nxt
    return best


def _line_rects(boxes: Sequence[Sequence[float]]) -> List[List[float]]:
    """
    Merges word boxes into one rectangle per line: words are grouped into rows by their
    vertical centre (OCR boxes of one line differ in height: "Today" vs "power"), then
    each row is joined left to right, split only where a wide gap separates columns.
    """
    rows: List[List[Sequence[float]]] = []
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        cy, h = (b[1] + b[3]) / 2, max(1.0, b[3] - b[1])
        if rows:
            row = rows[-1]
            row_cy = sum((r[1] + r[3]) / 2 for r in row) / len(row)
            row_h = max(max(1.0, r[3] - r[1]) for r in row)
            if abs(cy - row_cy) <= 0.5 * max(h, row_h):
                row.append(b)
                continue
        rows.append([b])
    rects: List[List[float]] = []
    for row in rows:
        row = sorted(row, key=lambda b: b[0])
        h = max(max(1.0, b[3] - b[1]) for b in row)
        current = [float(v) for v in row[0][:4]]
        for x0, y0, x1, y1 in (b[:4] for b in row[1:]):
            if x0 - current[2] < 3 * h:
                current = [min(current[0], x0), min(current[1], y0), max(current[2], x1), max(current[3], y1)]
            else:
                rects.append(current)
                current = [float(x0), float(y0), float(x1), float(y1)]
        rects.append(current)
    return rects


def align(quote: str, words: Sequence[Sequence[Any]]) -> Tuple[List[List[float]], float]:
    """
    Aligns the quote with page words [x0, y0, x1, y1, text]. Returns (line rectangles in
    page points, coverage = share of quote tokens matched).
    """
    quote_tokens = norm_tokens(quote)
    if not quote_tokens or not words:
        return [], 0.0
    flat: List[Tuple[str, Tuple[float, float, float, float]]] = []
    for w in words:
        for t in norm_tokens(str(w[4])):
            flat.append((t, (float(w[0]), float(w[1]), float(w[2]), float(w[3]))))
    page_tokens = [t for t, _ in flat]
    blocks = [b for b in SequenceMatcher(None, page_tokens, quote_tokens, autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return [], 0.0
    # Group matching blocks that lie close together on the page; keep the strongest group.
    groups: List[List[Any]] = []
    for b in sorted(blocks, key=lambda b: b.a):
        if groups and b.a - (groups[-1][-1].a + groups[-1][-1].size) <= 8:
            groups[-1].append(b)
        else:
            groups.append([b])
    best = max(groups, key=lambda g: sum(b.size for b in g))
    matched = sum(b.size for b in best)
    start, end = best[0].a, best[-1].a + best[-1].size
    boxes = [flat[i][1] for i in range(start, end)]
    return _line_rects(boxes), matched / float(len(quote_tokens))


def page_words(doc: Any, page_no: int, layout: Dict[str, Any]) -> List[List[Any]]:
    """Words of a page: OCR boxes for scanned pages, the PDF text layer otherwise."""
    ocr_words = (layout.get("ocr_words") or {}).get(str(page_no))
    if ocr_words:
        return ocr_words
    import fitz
    page = doc[page_no - 1]
    flags = fitz.TEXTFLAGS_WORDS & ~fitz.TEXT_PRESERVE_LIGATURES
    return [list(w[:5]) for w in page.get_text("words", flags=flags)]


def _normalised(rects: Sequence[Sequence[float]], width: float, height: float, pad: float) -> List[List[float]]:
    """Page-point rectangles, padded, as fractions of the page size."""
    return [[round(max(0.0, (x0 - pad) / width), 5), round(max(0.0, (y0 - pad) / height), 5),
             round(min(1.0, (x1 + pad) / width), 5), round(min(1.0, (y1 + pad) / height), 5)]
            for x0, y0, x1, y1 in rects]


def _passage_rects(doc: Any, layout: Dict[str, Any], page_no: int, passage: str,
                   chunk_id: str) -> Tuple[List[Sequence[float]], float]:
    """
    Rectangles of the whole cited passage and their padding: the chunk's boxes recorded at
    upload, else (older uploads) the start of the passage aligned with the page words.
    """
    boxes = [b[1:5] for b in (layout.get("chunks") or {}).get(chunk_id, []) if int(b[0]) == page_no]
    if boxes:
        return boxes, 3.0
    if passage:
        rects, coverage = align(" ".join(passage.split()[:60]), page_words(doc, page_no, layout))
        if rects and coverage >= 0.4:
            return rects, 1.5
    return [], 1.5


def _chunk_pages(layout: Dict[str, Any], chunk_id: str, page_no: int, page_count: int) -> List[int]:
    """The cited page first, then the other pages the chunk runs onto."""
    pages = [page_no]
    for b in (layout.get("chunks") or {}).get(chunk_id, []):
        p = int(b[0])
        if p not in pages and 1 <= p <= page_count:
            pages.append(p)
    return pages


def locate(doc: Any, layout: Dict[str, Any], page_no: int, passage: str = "", claim: str = "",
           chunk_id: str = "", table: Optional[Sequence[float]] = None, exact: bool = False) -> Dict[str, Any]:
    """
    Highlight rectangles for a citation. Returns {"page", "rects" (normalised), "quote",
    "method"}: "sentence" (the supporting sentence was found on the page), "passage" (the
    whole cited passage), "table", or "page" when nothing more precise is available.
    ``exact`` highlights the claim itself (a verbatim quote) instead of the passage sentence
    that best supports it. A passage that runs onto the next page is searched there too.
    """
    page_no = min(max(1, int(page_no or 1)), len(doc))

    def result(page: int, rects: Sequence[Sequence[float]], method: str, quote: str = "",
               pad: float = 1.5) -> Dict[str, Any]:
        rect = doc[page - 1].rect
        width, height = float(rect.width) or 1.0, float(rect.height) or 1.0
        return {"page": page, "rects": _normalised(rects, width, height, pad), "quote": quote, "method": method}

    if table:
        return result(page_no, [table[1:5]] if len(table) == 5 else [table], "table")

    quote = (claim.strip() if exact else best_sentence(passage, claim)) if claim else ""
    if quote:
        for page in _chunk_pages(layout, chunk_id, page_no, len(doc)):
            rects, coverage = align(quote, page_words(doc, page, layout))
            if rects and coverage >= (0.7 if exact else 0.5):
                return result(page, rects, "sentence", quote)

    rects, pad = _passage_rects(doc, layout, page_no, passage, chunk_id)
    return result(page_no, rects, "passage" if rects else "page", quote, pad)
