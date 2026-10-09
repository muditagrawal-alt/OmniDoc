"""
Table extraction helpers: clean cells, pick a header, reject layout grids that only look
like tables, find a caption, and read CSV / Excel files as tables.

A table is a dict:
    {"table_id", "page", "bbox", "title", "columns": [str], "rows": [[str]], "source"}
Cells stay as the text printed in the document; typing happens in the table store.
"""
import os
import re
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("OmniDoc.Tables")

MIN_COLS, MAX_COLS = 2, 40
MIN_FILLED_RATIO = 0.4
# Pages with more drawing operations than this are charts or infographics; table
# detection on them is slow and only finds plotting grids.
TABLE_MAX_DRAWINGS = int(os.getenv("OMNIDOC_TABLE_MAX_DRAWINGS", "1200"))
MAX_SHEET_ROWS = int(os.getenv("OMNIDOC_MAX_SHEET_ROWS", "200000"))

_NUMERIC_RE = re.compile(r"^[\s(+\-−$€£¥₹]*\d[\d,.\s]*%?[)\s]*$")


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN from pandas
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _is_numeric(cell: str) -> bool:
    return bool(cell) and bool(_NUMERIC_RE.match(cell))


def _looks_like_header(row: Sequence[str]) -> bool:
    filled = [c for c in row if c]
    if len(filled) < max(1, len(row) // 2):
        return False
    return sum(_is_numeric(c) for c in filled) <= len(filled) // 3


def _unique(names: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out = []
    for i, name in enumerate(names):
        base = name or f"Column {i + 1}"
        key = base.lower()
        if key in seen:
            seen[key] += 1
            base = f"{base} {seen[key]}"
        else:
            seen[key] = 1
        out.append(base)
    return out


def normalize_table(header: Optional[Sequence[Any]], rows: Sequence[Sequence[Any]],
                    min_rows: int = 2) -> Optional[Tuple[List[str], List[List[str]]]]:
    """
    Cleans a raw table. Returns (columns, rows) or None when it is not a usable table
    (too few rows or columns, mostly empty, or a plotting grid).
    """
    body = [[clean_cell(c) for c in r] for r in rows if r is not None]
    head = [clean_cell(c) for c in header] if header else None
    width = max([len(r) for r in body] + [len(head) if head else 0] or [0])
    if width == 0:
        return None
    body = [r + [""] * (width - len(r)) for r in body]
    if head is not None:
        head = head + [""] * (width - len(head))

    # Header: explicit names unless mostly blank, else the first row if it reads like one.
    if not head or sum(bool(c) for c in head) < max(1, width // 2):
        head = None
        if body and _looks_like_header(body[0]):
            head, body = body[0], body[1:]
    elif body and [c.lower() for c in body[0]] == [c.lower() for c in head]:
        body = body[1:]  # header repeated as the first row

    body = [r for r in body if any(r)]
    # Drop columns that are empty everywhere.
    keep = [j for j in range(width) if (head and head[j]) or any(r[j] for r in body)]
    if not keep:
        return None
    body = [[r[j] for j in keep] for r in body]
    columns = _unique([(head[j] if head else "") for j in keep])

    n_cols = len(columns)
    if n_cols < MIN_COLS or n_cols > MAX_COLS or len(body) < min_rows:
        return None
    filled = sum(bool(c) for r in body for c in r)
    if filled / float(n_cols * len(body)) < MIN_FILLED_RATIO:
        return None
    return columns, body


def table_caption(page: Any, bbox: Sequence[float]) -> str:
    """The text line right above a table (a "Table 3: ..." caption if there is one)."""
    try:
        x0, y0, x1, _ = bbox
        best, best_gap = "", 1e9
        for b in page.get_text("blocks"):
            bx0, by0, bx1, by1, text = b[0], b[1], b[2], b[3], str(b[4])
            gap = y0 - by1
            if 0 <= gap <= 60 and bx1 > x0 and bx0 < x1:
                line = clean_cell(text.strip().splitlines()[-1] if text.strip() else "")
                if not line or len(line) > 140:
                    continue
                score = gap - (40 if re.match(r"^(table|tab\.)\s*\d", line, re.I) else 0)
                if score < best_gap:
                    best, best_gap = line, score
        return best
    except Exception:
        return ""


def table_markdown(columns: List[str], rows: List[List[str]], max_rows: int = 40) -> str:
    def esc(c: str) -> str:
        return c.replace("|", "\\|")
    out = ["| " + " | ".join(esc(c) for c in columns) + " |", "|" + "---|" * len(columns)]
    for r in rows[:max_rows]:
        out.append("| " + " | ".join(esc(c) for c in r) + " |")
    if len(rows) > max_rows:
        out.append(f"(+{len(rows) - max_rows} more rows)")
    return "\n".join(out)


def table_text_blocks(table: Dict[str, Any], rows_per_block: int = 25, max_rows: int = 300) -> List[str]:
    """
    Readable text for the search index: rows written as "column: value" pairs, so a
    question about a value can find the row even though SQL answers it.
    """
    title = table.get("title") or "Table"
    columns = table["columns"]
    rows = table["rows"][:max_rows]
    header = f"{title}. Columns: {', '.join(columns)}. {len(table['rows'])} rows."
    blocks = []
    for start in range(0, len(rows), rows_per_block):
        lines = [header] if start == 0 else [f"{title} (continued)."]
        for r in rows[start:start + rows_per_block]:
            pairs = [f"{c}: {v}" for c, v in zip(columns, r) if v]
            if pairs:
                lines.append("; ".join(pairs) + ".")
        blocks.append("\n".join(lines))
    return blocks or [header]


def read_spreadsheet(path: str) -> List[Tuple[str, List[str], List[List[str]]]]:
    """CSV / TSV / Excel sheets as (sheet title, columns, rows); cells kept as text."""
    import pandas as pd

    ext = os.path.splitext(path)[1].lower()
    frames: List[Tuple[str, Any]] = []
    if ext in (".csv", ".tsv"):
        frame = None
        for enc in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                frame = pd.read_csv(path, sep="\t" if ext == ".tsv" else None, engine="python",
                                    dtype=str, keep_default_na=False, encoding=enc, nrows=MAX_SHEET_ROWS)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if frame is not None:
            frames.append((os.path.splitext(os.path.basename(path))[0], frame))
    else:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str, keep_default_na=False, engine="openpyxl",
                               nrows=MAX_SHEET_ROWS)
        frames.extend((str(name), frame) for name, frame in sheets.items())

    out = []
    for title, frame in frames:
        if frame is None or frame.empty:
            continue
        columns = [clean_cell(c) for c in frame.columns]
        columns = ["" if re.match(r"^Unnamed: \d+$", c) else c for c in columns]
        rows = [[clean_cell(v) for v in row] for row in frame.itertuples(index=False, name=None)]
        norm = normalize_table(columns, rows, min_rows=1)
        if norm:
            out.append((title, norm[0], norm[1]))
    return out
