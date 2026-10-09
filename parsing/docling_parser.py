"""
Docling Document Parser for OmniDoc.
Converts PDF and DOCX into structured Markdown ASTs, extracting tables,
figure bounding boxes, and hierarchical section-aware chunks.

Fast mode (used for uploads) reads PDFs with PyMuPDF, OCRs pages that have no text
layer (scans and photos, see parsing/ocr.py), records where every chunk sits on its page
(so a citation can be highlighted in the original), and extracts tables for SQL
questions. Word files, CSV / Excel sheets, Markdown and plain text are supported too.
"""
import os
import re
import uuid
import logging
from collections import Counter
from typing import List, Dict, Any, Optional, Sequence, Set, Tuple
from dataclasses import dataclass, field

from core.state import RetrievedChunk, VisualElement
from parsing import ocr
from parsing import formats
from parsing.tables import (
    TABLE_MAX_DRAWINGS,
    normalize_table,
    read_spreadsheet,
    table_caption,
    table_markdown,
    table_text_blocks,
)

logger = logging.getLogger("OmniDoc.DoclingParser")

# (page, section, text) or (page, section, text, (x0, y0, x1, y1)) in PDF points
Block = Tuple[Any, ...]


@dataclass
class ParsedDocument:
    doc_id: str
    filename: str
    markdown_content: str
    chunks: List[RetrievedChunk]
    visual_elements: List[VisualElement]
    tables: List[Dict[str, Any]]
    # Page sizes, chunk boxes and OCR word boxes, used to highlight citations.
    layout: Dict[str, Any] = field(default_factory=dict)
    ocr_pages: List[int] = field(default_factory=list)
    ocr_languages: List[str] = field(default_factory=list)


class DoclingParser:
    """Parses documents with layout awareness using IBM Docling."""

    def __init__(self, extracted_images_dir: str = "extracted_images"):
        self.images_dir = extracted_images_dir
        os.makedirs(self.images_dir, exist_ok=True)
        self.converter = None
        self._init_converter()

    def _init_converter(self):
        try:
            from docling.document_converter import DocumentConverter
            self.converter = DocumentConverter()
            logger.info("Docling DocumentConverter ready.")
        except Exception as e:
            logger.warning(f"Docling initialization notice: {e}. PyMuPDF fallback available.")

    def parse_document(self, file_path: str, doc_id: Optional[str] = None, fast_mode: bool = False) -> ParsedDocument:
        """
        Parses a PDF or DOCX file into structured text, tables, and figures.
        If fast_mode=True, uses instant PyMuPDF parsing for real-time JIT interactive ingestion.
        """
        filename = os.path.basename(file_path)
        doc_id = doc_id or f"doc_{uuid.uuid4().hex[:10]}"
        ext = os.path.splitext(file_path)[1].lower()

        if not fast_mode and self.converter and ext in (".pdf", ".docx"):
            try:
                parsed = self._parse_with_docling(file_path, doc_id, filename)
                if parsed.chunks:
                    return parsed
                logger.info(f"Docling found no text in {filename}; trying OCR in fast mode.")
            except Exception as e:
                logger.error(f"Docling parsing failed on {filename} ({e}). Using PyMuPDF fallback.")

        return self._parse_with_pymupdf_fallback(file_path, doc_id, filename)

    def _parse_with_docling(self, file_path: str, doc_id: str, filename: str) -> ParsedDocument:
        """Primary Docling conversion path with HybridChunker."""
        from docling.chunking import HybridChunker

        conv_res = self.converter.convert(file_path)
        doc = conv_res.document
        markdown_text = doc.export_to_markdown()

        # Extract hierarchical chunks
        chunker = HybridChunker(max_tokens=500)
        chunk_iter = chunker.chunk(doc)

        chunks: List[RetrievedChunk] = []
        for i, ch in enumerate(chunk_iter, 1):
            text = ch.text.strip()
            if not text:
                continue

            # Extract section heading if available in metadata
            section = "General"
            if hasattr(ch, "meta") and ch.meta:
                headings = getattr(ch.meta, "headings", [])
                if headings:
                    section = " > ".join(headings)

            page_num = 1
            if hasattr(ch, "meta") and hasattr(ch.meta, "doc_items"):
                items = ch.meta.doc_items
                if items and hasattr(items[0], "prov") and items[0].prov:
                    page_num = items[0].prov[0].page_no

            chunks.append(RetrievedChunk(
                chunk_id=f"{doc_id}_c{i:03d}",
                doc_id=doc_id,
                text=text,
                page_number=page_num,
                section_title=section,
                score=0.0,
                retrieval_method="hybrid"
            ))

        tables: List[Dict[str, Any]] = []
        for i, tbl in enumerate(getattr(doc, "tables", []), 1):
            try:
                frame = tbl.export_to_dataframe()
                norm = normalize_table([str(c) for c in frame.columns],
                                       [list(r) for r in frame.itertuples(index=False, name=None)])
                if norm:
                    tables.append(_table(doc_id, len(tables) + 1, _prov_page(tbl), None, "", norm, "docling"))
            except Exception:
                pass

        # Extract figures
        visual_elements: List[VisualElement] = []
        page_captions: Dict[int, str] = {}
        for i, fig in enumerate(getattr(doc, "pictures", []), 1):
            fig_id = f"{doc_id}_fig_{i}"
            caption = ""
            try:
                caption = fig.caption_text(doc) or ""
            except Exception:
                caption = ""
            if caption:
                page_captions.setdefault(_prov_page(fig), caption)
            caption = caption or f"Figure {i} in {filename}"
            bbox = None
            if hasattr(fig, "prov") and fig.prov:
                b = fig.prov[0].bbox
                bbox = [b.l, b.t, b.r, b.b] if b else None

            visual_elements.append(VisualElement(
                figure_id=fig_id,
                doc_id=doc_id,
                page_number=_prov_page(fig),
                caption=caption,
                image_path=None,
                bounding_box=bbox
            ))

        layout: Dict[str, Any] = {}
        # Docling locates figures but does not save them; save the PDF's embedded images
        # so the vision agent can read them, keeping Docling's captions where it found one.
        if os.path.splitext(filename)[1].lower() == ".pdf":
            try:
                with ocr.open_as_pdf(file_path) as pdf:
                    layout["pages"] = [{"w": round(p.rect.width, 1), "h": round(p.rect.height, 1), "ocr": False,
                                        "lang": None} for p in pdf]
                    saved = self._pdf_images(pdf, doc_id, filename)
                for v in saved:
                    v.caption = page_captions.get(v.page_number, v.caption)
                visual_elements = saved or visual_elements
            except Exception as e:
                logger.warning(f"Figure extraction skipped for {filename}: {e}")

        return ParsedDocument(
            doc_id=doc_id,
            filename=filename,
            markdown_content=markdown_text,
            chunks=chunks,
            visual_elements=visual_elements,
            tables=tables,
            layout=layout,
        )

    # ------------------------------------------------------------------
    # Fast mode (PyMuPDF / python-docx / spreadsheets / plain text)
    # ------------------------------------------------------------------

    def _parse_with_pymupdf_fallback(self, file_path: str, doc_id: str, filename: str) -> ParsedDocument:
        """
        Fast structured parsing without Docling: PDFs and images via PyMuPDF (section titles
        from font sizes, running headers/footers removed, de-hyphenation, OCR for pages
        without text, tables), DOCX via python-docx (heading styles and tables in document
        order), CSV / Excel sheets as tables, Markdown headings, plain text.
        """
        ext = os.path.splitext(file_path)[1].lower()
        tables: List[Dict[str, Any]] = []
        visual_elements: List[VisualElement] = []
        layout: Dict[str, Any] = {}
        paged = ext == ".pdf" or ext in ocr.IMAGE_EXTENSIONS

        if paged:
            with ocr.open_as_pdf(file_path) as pdf:
                found: Dict[int, List[Tuple[List[float], Any]]] = {}
                blocks, layout = self._pdf_blocks(pdf, found_tables=found)
                ocr_pages = {i + 1 for i, p in enumerate(layout["pages"]) if p.get("ocr")}
                tables = self._pdf_tables(pdf, doc_id, skip_pages=ocr_pages, found=found)
                visual_elements = self._pdf_images(pdf, doc_id, filename, scanned_pages=ocr_pages)
        elif ext == ".docx":
            blocks, tables = self._docx_blocks(file_path, doc_id)
        elif ext in SPREADSHEET_EXTENSIONS:
            blocks, tables = self._spreadsheet_blocks(file_path, doc_id)
        elif ext == ".pptx":
            blocks, slide_tables = formats.pptx_blocks(file_path)
            for t in slide_tables:
                norm = normalize_table(t["columns"], t["rows"])
                if norm:
                    tables.append(_table(doc_id, len(tables) + 1, t["page"], None, t["title"], norm, "pptx"))
        elif ext == ".eml":
            blocks, attachments = formats.eml_blocks(file_path)
            layout["attachments"] = attachments
        elif ext == ".epub":
            blocks = formats.epub_blocks(file_path)
        elif ext in (".html", ".htm"):
            blocks = formats.html_blocks(file_path)
        elif ext in formats.MEDIA_EXTENSIONS:
            blocks, layout["media"] = formats.media_blocks(file_path)
        elif ext in TEXT_EXTENSIONS:
            blocks = self._text_blocks(file_path, markdown=ext in (".md", ".markdown"))
        else:
            blocks = self._unknown_blocks(file_path)

        boxes: Dict[str, List[List[float]]] = {}
        chunks = chunk_blocks(doc_id, blocks, paged=paged or ext in (".pptx", ".epub"), boxes_out=boxes)
        if layout.get("media"):
            # Where each passage starts in the recording, so a citation can play from there.
            layout["media"]["chunk_starts"] = {c.chunk_id: formats.section_start(c.section_title or "") for c in chunks}
        if not chunks:
            logger.warning(f"No extractable text found in {filename} (blank, encrypted or unreadable?).")
        if paged:
            layout["chunks"] = boxes
            layout["tables"] = {t["table_id"]: [t["page"]] + list(t["bbox"]) for t in tables if t.get("bbox")}
        ocr_pages = [i + 1 for i, p in enumerate(layout.get("pages", [])) if p.get("ocr")]
        languages = sorted({p["lang"] for p in layout.get("pages", []) if p.get("lang")})
        if ocr_pages:
            logger.info(f"OCR read {len(ocr_pages)} page(s) of {filename} ({', '.join(languages)}).")
        markdown = self._blocks_to_markdown(blocks)
        return ParsedDocument(
            doc_id=doc_id,
            filename=filename,
            markdown_content=markdown,
            chunks=chunks,
            visual_elements=visual_elements,
            tables=tables,
            layout=layout,
            ocr_pages=ocr_pages,
            ocr_languages=languages,
        )

    def _pdf_images(self, doc: Any, doc_id: str, filename: str,
                    scanned_pages: Optional[Set[int]] = None) -> List[VisualElement]:
        """
        Saves embedded figures (>= MIN_FIGURE_PX on both sides) to
        ``<images_dir>/<doc_id>/p<page>_img<k>.png`` and renders pages dominated by vector
        graphics (charts, diagrams) to ``p<page>_page.png``, so the vision agent can inspect
        the figures of a specific document. On scanned pages the page image itself is kept
        (it may hold charts) but captioned as the page, not as a figure. Failures never break
        ingestion.
        """
        elements: List[VisualElement] = []
        if not re.match(r"^[A-Za-z0-9_\-.]+$", doc_id or ""):
            return elements
        try:
            import fitz
            out_dir = os.path.join(self.images_dir, doc_id)
            seen = set()
            renders = 0
            for page_no, page in enumerate(doc, 1):
                if renders < MAX_PAGE_RENDERS_PER_DOC and len(elements) < MAX_FIGURES_PER_DOC:
                    try:
                        vector_heavy = len(page.get_drawings()) >= VECTOR_PAGE_MIN_DRAWINGS
                    except Exception:
                        vector_heavy = False
                    if vector_heavy:
                        os.makedirs(out_dir, exist_ok=True)
                        path = os.path.join(out_dir, f"p{page_no}_page.png")
                        page.get_pixmap(matrix=fitz.Matrix(PAGE_RENDER_ZOOM, PAGE_RENDER_ZOOM)).save(path)
                        renders += 1
                        elements.append(VisualElement(
                            figure_id=f"{doc_id}_p{page_no}_page",
                            doc_id=doc_id,
                            page_number=page_no,
                            caption=f"Page {page_no} of {filename} (charts or diagrams)",
                            image_path=path,
                        ))
                for k, img in enumerate(page.get_images(full=True)):
                    xref = img[0]
                    if xref in seen or len(elements) >= MAX_FIGURES_PER_DOC:
                        continue
                    seen.add(xref)
                    pix = fitz.Pixmap(doc, xref)
                    if pix.width < MIN_FIGURE_PX or pix.height < MIN_FIGURE_PX:
                        continue
                    if pix.n - pix.alpha >= 4 or pix.alpha:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    os.makedirs(out_dir, exist_ok=True)
                    path = os.path.join(out_dir, f"p{page_no}_img{k}.png")
                    pix.save(path)
                    scan = page_no in (scanned_pages or ()) and _covers_page(page, xref)
                    elements.append(VisualElement(
                        figure_id=f"{doc_id}_p{page_no}_img{k}",
                        doc_id=doc_id,
                        page_number=page_no,
                        caption=f"Page {page_no} of {filename} (scanned)" if scan else f"Figure on page {page_no} of {filename}",
                        image_path=path,
                    ))
        except Exception as e:
            logger.warning(f"Figure extraction skipped for {filename}: {e}")
        return elements

    @staticmethod
    def _page_tables(page: Any) -> List[Tuple[List[float], Any]]:
        """
        (bbox, normalised table) for each table PyMuPDF finds on a page; none on chart-heavy
        pages. Rows are read while the page is loaded: tables kept past it read back wrong.
        """
        try:
            if len(page.get_drawings()) > TABLE_MAX_DRAWINGS:
                return []
            found = page.find_tables().tables
        except Exception:
            return []
        out = []
        for tb in found:
            try:
                rows = tb.extract()
                header = tb.header
                names = list(header.names) if header is not None else None
                if header is not None and not header.external and rows:
                    names, rows = rows[0], rows[1:]
                norm = normalize_table(names, rows)
            except Exception:
                continue
            if norm:
                out.append(([round(v, 1) for v in tb.bbox], norm))
        return out

    @classmethod
    def _pdf_tables(cls, doc: Any, doc_id: str, skip_pages: Set[int],
                    found: Optional[Dict[int, List[Tuple[List[float], Any]]]] = None) -> List[Dict[str, Any]]:
        """
        Ruled and aligned tables on text pages (OCR'd pages and chart pages are skipped);
        ``found`` holds the tables already read per page while the text was read.
        """
        tables: List[Dict[str, Any]] = []
        for page_no, page in enumerate(doc, 1):
            if page_no in skip_pages:
                continue
            page_tables = found[page_no] if found is not None and page_no in found else cls._page_tables(page)
            for bbox, norm in page_tables:
                tables.append(_table(doc_id, len(tables) + 1, page_no, bbox, table_caption(page, bbox), norm, "pdf"))
        return tables

    @staticmethod
    def _blocks_to_markdown(blocks: List[Block]) -> str:
        parts, last_section = [], None
        for blk in blocks:
            section, text = blk[1], blk[2]
            if section and section != last_section:
                parts.append(f"## {section}")
                last_section = section
            parts.append(text)
        return "\n\n".join(parts)

    def _pdf_blocks(self, doc: Any, found_tables: Optional[Dict[int, List[Tuple[List[float], Any]]]] = None
                    ) -> Tuple[List[Block], Dict[str, Any]]:
        """
        Paragraph blocks with their position, plus page sizes and OCR word boxes. Tables found
        on text pages go into ``found_tables``; lines inside them (a bold "Book | Author" header
        row) are never taken for headings, so the heading above the table stays the section.
        """
        import fitz
        flags = (fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_LIGATURES & ~fitz.TEXT_PRESERVE_IMAGES)
        pages = []
        size_weight: Counter = Counter()
        margin_counts: Counter = Counter()
        layout: Dict[str, Any] = {"pages": [], "ocr_words": {}}
        ocr_count = 0
        for page_no, page in enumerate(doc, 1):
            height = float(page.rect.height) or 1.0
            page_dict = page.get_text("dict", flags=flags)
            chars = sum(len(sp.get("text", "").strip())
                        for b in page_dict.get("blocks", []) if b.get("type") == 0
                        for ln in b.get("lines", []) for sp in ln.get("spans", []))
            ocr_lang = None
            if ocr_count < ocr.MAX_OCR_PAGES and ocr.page_needs_ocr(page, chars):
                result = ocr.ocr_page(page)
                if result is not None:
                    page_dict = {"blocks": result["blocks"]}
                    layout["ocr_words"][str(page_no)] = result["words"]
                    ocr_lang = result["language"]
                    ocr_count += 1
            layout["pages"].append({"w": round(page.rect.width, 1), "h": round(page.rect.height, 1),
                                    "ocr": ocr_lang is not None, "lang": ocr_lang})
            table_boxes: List[Sequence[float]] = []
            if ocr_lang is None:
                page_tables = self._page_tables(page)
                if found_tables is not None:
                    found_tables[page_no] = page_tables
                table_boxes = [bbox for bbox, _ in page_tables]

            lines = []
            for b in page_dict.get("blocks", []):
                if b.get("type") != 0:
                    continue
                block_lines = []
                for ln in b.get("lines", []):
                    spans = [sp for sp in ln.get("spans", []) if sp.get("text", "").strip()]
                    if not spans:
                        continue
                    text = "".join(sp["text"] for sp in spans).strip()
                    size = max(float(sp.get("size", 0)) for sp in spans)
                    bold = any((sp.get("flags", 0) & 16) or re.search(r"bold|black|heavy", sp.get("font", ""), re.I) for sp in spans)
                    y0, y1 = ln["bbox"][1], ln["bbox"][3]
                    in_margin = y1 < 0.06 * height or y0 > 0.94 * height
                    for sp in spans:
                        size_weight[round(float(sp.get("size", 0)) * 2) / 2] += len(sp["text"].strip())
                    if in_margin:
                        margin_counts[_margin_key(text)] += 1
                    cx, cy = (ln["bbox"][0] + ln["bbox"][2]) / 2, (y0 + y1) / 2
                    in_table = any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in table_boxes)
                    block_lines.append({"text": text, "size": size, "bold": bool(bold), "margin": in_margin,
                                        "bbox": tuple(ln["bbox"]), "ocr": ocr_lang is not None, "table": in_table})
                if block_lines:
                    lines.append(block_lines)
            pages.append(lines)

        body = size_weight.most_common(1)[0][0] if size_weight else 10.0
        repeat_threshold = 2 if len(pages) <= 4 else 3
        blocks: List[Block] = []
        section = ""
        for page_no, page_blocks in enumerate(pages, 1):
            if not page_blocks:
                logger.info(f"Page {page_no} has no extractable text (blank page or failed OCR).")
            for block_lines in page_blocks:
                para: List[Dict[str, Any]] = []
                heading: List[str] = []

                def flush_para():
                    if para:
                        blocks.append((page_no, section, _join_lines([p["text"] for p in para]),
                                       _union([p["bbox"] for p in para])))
                        para.clear()

                for ln in block_lines:
                    text = ln["text"]
                    if ln["margin"] and margin_counts[_margin_key(text)] >= repeat_threshold:
                        continue  # running header / footer / page number
                    # OCR sizes are estimates, so scanned lines must stand out more to count as headings
                    # (a heading's text leaves the passage and becomes its section title).
                    is_heading = (
                        not ln["margin"]
                        and not ln["table"]
                        and _looks_like_heading(text)
                        and (ln["size"] >= body * (OCR_HEADING_RATIO if ln["ocr"] else 1.18)
                             or (ln["bold"] and ln["size"] >= body and len(text.split()) <= 8))
                    )
                    if is_heading:
                        flush_para()
                        heading.append(text)
                        continue
                    if heading:
                        section = " ".join(heading)[:120]
                        heading = []
                    para.append(ln)
                if heading:
                    section = " ".join(heading)[:120]
                flush_para()
        return blocks, layout

    @staticmethod
    def _docx_blocks(file_path: str, doc_id: str = "") -> Tuple[List[Block], List[Dict[str, Any]]]:
        blocks: List[Block] = []
        tables: List[Dict[str, Any]] = []
        try:
            import docx
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except Exception as e:
            logger.warning(f"python-docx unavailable ({e}); cannot parse {file_path} in fast mode.")
            return blocks, tables
        document = docx.Document(file_path)
        section = ""
        for child in document.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                para = Paragraph(child, document)
                text = para.text.strip()
                if not text:
                    continue
                style = (para.style.name if para.style is not None else "") or ""
                runs = [r for r in para.runs if r.text.strip()]
                all_bold = bool(runs) and all(bool(r.bold) for r in runs)
                short = len(text.split()) <= 10 and not text.endswith((".", ",", ";", ":"))
                numbered = bool(re.match(r"^\d+(\.\d+)*\.?\s+[A-Za-z]", text))
                if style.lower().startswith("heading") or style.lower() == "title" or (short and (all_bold or numbered)):
                    section = text[:120]
                    continue
                blocks.append((1, section, text))
            elif tag == "tbl":
                table = Table(child, document)
                rows, raw_rows = [], []
                for row in table.rows:
                    cells = []
                    for cell in row.cells:
                        ct = " ".join(cell.text.split())
                        if not cells or cells[-1] != ct:  # merged cells repeat their text
                            cells.append(ct)
                    if any(cells):
                        rows.append(" | ".join(cells))
                        raw_rows.append([" ".join(c.text.split()) for c in row.cells])
                if rows:
                    blocks.append((1, section, "\n".join(rows)))
                norm = normalize_table(None, raw_rows)
                if norm:
                    tables.append(_table(doc_id, len(tables) + 1, None, None, section, norm, "docx"))
        return blocks, tables

    @staticmethod
    def _spreadsheet_blocks(file_path: str, doc_id: str) -> Tuple[List[Block], List[Dict[str, Any]]]:
        """Each sheet becomes a table for SQL plus readable row text for search."""
        blocks: List[Block] = []
        tables: List[Dict[str, Any]] = []
        try:
            sheets = read_spreadsheet(file_path)
        except Exception as e:
            logger.warning(f"Could not read spreadsheet {file_path}: {e}")
            return blocks, tables
        for title, columns, rows in sheets:
            t = _table(doc_id, len(tables) + 1, None, None, title, (columns, rows), "sheet")
            tables.append(t)
            for text in table_text_blocks(t):
                blocks.append((1, title, text))
        return blocks, tables

    @staticmethod
    def _read_text(file_path: str) -> str:
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                with open(file_path, "r", encoding=enc) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def _text_blocks(self, file_path: str, markdown: bool = False) -> List[Block]:
        text = self._read_text(file_path)
        blocks: List[Block] = []
        section = ""
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if not para:
                continue
            if markdown:
                lines = para.splitlines()
                body = []
                for line in lines:
                    m = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
                    if m:
                        if body:
                            blocks.append((1, section, "\n".join(body)))
                            body = []
                        section = m.group(1).strip()[:120]
                    else:
                        body.append(line)
                if body:
                    blocks.append((1, section, "\n".join(body)))
            else:
                blocks.append((1, section, para))
        return blocks

    def _unknown_blocks(self, file_path: str) -> List[Block]:
        """Reads unknown formats only if they are actually text (never indexes binary noise)."""
        with open(file_path, "rb") as f:
            head = f.read(4096)
        if b"\x00" in head:
            logger.warning(f"Unsupported binary format for fast parsing: {file_path}")
            return []
        return self._text_blocks(file_path)


def _table(doc_id: str, k: int, page: Optional[int], bbox: Optional[List[float]], title: str,
           norm: Tuple[List[str], List[List[str]]], source: str) -> Dict[str, Any]:
    columns, rows = norm
    return {
        "table_id": f"{doc_id}_t{k}",
        "page": page,
        "bbox": bbox,
        "title": title or (f"Table {k} on page {page}" if page else f"Table {k}"),
        "columns": columns,
        "rows": rows,
        "source": source,
        "markdown": table_markdown(columns, rows),
    }


def _covers_page(page: Any, xref: int) -> bool:
    """True when an image fills most of the page (a scan rather than a figure)."""
    try:
        area = abs(page.rect) or 1.0
        return any(abs(r & page.rect) >= 0.8 * area for r in page.get_image_rects(xref))
    except Exception:
        return False


def _union(boxes: Sequence[Sequence[float]]) -> Optional[Tuple[float, float, float, float]]:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (round(min(b[0] for b in boxes), 1), round(min(b[1] for b in boxes), 1),
            round(max(b[2] for b in boxes), 1), round(max(b[3] for b in boxes), 1))


def _prov_page(item: Any) -> int:
    """Page number from a Docling item's provenance (1 if unknown)."""
    try:
        prov = getattr(item, "prov", None) or []
        return int(prov[0].page_no) if prov else 1
    except Exception:
        return 1


TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".log", ".yaml", ".yml", ".xml", ".html", ".htm", ".rst"}
SPREADSHEET_EXTENSIONS = {".csv", ".tsv", ".xlsx"}
CHUNK_MAX_WORDS = 300
OCR_HEADING_RATIO = 1.4
MIN_FIGURE_PX = 150
MAX_FIGURES_PER_DOC = 40
# Charts and infographics are often vector drawings that get_images() cannot see;
# pages with at least this many drawing operations are rendered whole instead.
VECTOR_PAGE_MIN_DRAWINGS = 60
MAX_PAGE_RENDERS_PER_DOC = 24
PAGE_RENDER_ZOOM = 1.5
CHUNK_OVERLAP_WORDS = 40
CHUNK_MIN_WORDS = 40


def _margin_key(text: str) -> str:
    return re.sub(r"\d+", "#", " ".join(text.lower().split()))


def _looks_like_heading(text: str) -> bool:
    words = text.split()
    letters = sum(ch.isalpha() for ch in text)
    return (
        1 <= len(words) <= 12
        and len(text) <= 100
        and letters >= 3
        and not text.rstrip().endswith((",", ";"))
        and not re.fullmatch(r"[\d\W]+", text)
    )


def _join_lines(lines: List[str]) -> str:
    """Joins PDF lines, removing end-of-line hyphenation ("im-" + "plement")."""
    out = ""
    for line in lines:
        line = line.strip()
        if not out:
            out = line
        elif out.endswith("-") and line[:1].islower():
            out = out[:-1] + line
        else:
            out = out + " " + line
    return re.sub(r"\s+", " ", out).strip()


def chunk_blocks(doc_id: str, blocks: List[Block], paged: bool = True,
                 boxes_out: Optional[Dict[str, List[List[float]]]] = None) -> List[RetrievedChunk]:
    """
    Packs (page, section, text[, bbox]) blocks into chunks of <= CHUNK_MAX_WORDS words
    without crossing page boundaries; a new section starts a new chunk once the current one
    has CHUNK_MIN_WORDS words; very long blocks are windowed with CHUNK_OVERLAP_WORDS overlap.
    When ``boxes_out`` is given it receives, per chunk id, the [page, x0, y0, x1, y1] boxes
    of the blocks the chunk was built from.
    """
    chunks: List[RetrievedChunk] = []
    counters: Dict[int, int] = {}
    cur_words: List[str] = []
    cur_boxes: List[Tuple[float, ...]] = []
    cur_page, cur_section = None, ""
    last_section = ""  # section of the last block added to the current chunk

    def emit():
        nonlocal cur_words, cur_boxes
        if not cur_words:
            return
        k = counters.get(cur_page, 0)
        counters[cur_page] = k + 1
        chunk_id = f"{doc_id}_p{cur_page}_c{k}"
        chunks.append(RetrievedChunk(
            chunk_id=chunk_id,
            doc_id=doc_id,
            text=" ".join(cur_words),
            page_number=int(cur_page or 1),
            section_title=cur_section or (f"Page {cur_page}" if paged else "General"),
            score=0.0,
            retrieval_method="hybrid"
        ))
        if boxes_out is not None and cur_boxes:
            unique = list(dict.fromkeys(cur_boxes))
            boxes_out[chunk_id] = [[int(cur_page or 1)] + list(b) for b in unique]
        cur_words, cur_boxes = [], []

    for blk in blocks:
        page, section, text = blk[0], blk[1], blk[2]
        bbox = tuple(blk[3]) if len(blk) > 3 and blk[3] else None
        words = text.split()
        if not words:
            continue
        if cur_page is not None and page != cur_page:
            emit()
        elif section != cur_section and len(cur_words) >= CHUNK_MIN_WORDS:
            emit()
        if not cur_words:
            cur_page, cur_section = page, section
        elif section and section != last_section:
            # Sections too short for a chunk of their own share one: keep each later heading in
            # the text ("Stage 2 — Ancient Civilizations and Empires"), or it is lost to search.
            words = section.split() + words
        last_section = section
        if len(cur_words) + len(words) <= CHUNK_MAX_WORDS:
            cur_words.extend(words)
            if bbox:
                cur_boxes.append(bbox)
            continue
        if len(words) <= CHUNK_MAX_WORDS:
            emit()
            cur_page, cur_section = page, section
            cur_words = list(words)
            cur_boxes = [bbox] if bbox else []
            continue
        # Long block: fill the current chunk, then window the rest with overlap.
        emit()
        cur_page, cur_section = page, section
        step = CHUNK_MAX_WORDS - CHUNK_OVERLAP_WORDS
        start = 0
        while start < len(words):
            window = words[start:start + CHUNK_MAX_WORDS]
            if start > 0 and len(window) <= CHUNK_OVERLAP_WORDS:
                break  # tail already covered by the previous window's overlap
            cur_words = list(window)
            cur_boxes = [bbox] if bbox else []
            if start + CHUNK_MAX_WORDS >= len(words):
                break  # keep the last window open so short following blocks can join it
            emit()
            cur_page, cur_section = page, section
            start += step
    emit()
    return _merge_tiny(chunks, boxes_out)


def _merge_tiny(chunks: List[RetrievedChunk],
                boxes_out: Optional[Dict[str, List[List[float]]]] = None) -> List[RetrievedChunk]:
    """Folds fragments (< CHUNK_MIN_WORDS / 2 words) into the previous chunk of the same page."""
    out: List[RetrievedChunk] = []
    for ch in chunks:
        n = len(ch.text.split())
        if (out and n < CHUNK_MIN_WORDS // 2 and out[-1].page_number == ch.page_number
                and len(out[-1].text.split()) + n <= CHUNK_MAX_WORDS + CHUNK_OVERLAP_WORDS):
            # The fragment's heading stays in the text, or it is lost with the fragment's section.
            heading = ch.section_title if ch.section_title != out[-1].section_title and \
                not re.fullmatch(r"Page \d+|General", ch.section_title) and \
                ch.section_title not in out[-1].text and not ch.text.startswith(ch.section_title) else ""
            out[-1] = out[-1].model_copy(update={"text": " ".join(filter(None, (out[-1].text, heading, ch.text)))})
            if boxes_out is not None and ch.chunk_id in boxes_out:
                boxes_out.setdefault(out[-1].chunk_id, []).extend(boxes_out.pop(ch.chunk_id))
            continue
        out.append(ch)
    return out
