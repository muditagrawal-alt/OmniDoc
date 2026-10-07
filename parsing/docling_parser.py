"""
Docling Document Parser for OmniDoc.
Converts PDF and DOCX into structured Markdown ASTs, extracting tables,
figure bounding boxes, and hierarchical section-aware chunks.
"""
import os
import re
import uuid
import logging
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from core.state import RetrievedChunk, VisualElement

logger = logging.getLogger("OmniDoc.DoclingParser")


@dataclass
class ParsedDocument:
    doc_id: str
    filename: str
    markdown_content: str
    chunks: List[RetrievedChunk]
    visual_elements: List[VisualElement]
    tables: List[Dict[str, Any]]


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

        if not fast_mode and self.converter:
            try:
                return self._parse_with_docling(file_path, doc_id, filename)
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

        # Extract tables
        tables = []
        for i, tbl in enumerate(getattr(doc, "tables", []), 1):
            try:
                try:
                    tbl_md = tbl.export_to_markdown(doc=doc)
                except TypeError:
                    tbl_md = tbl.export_to_markdown()
                tables.append({
                    "table_id": f"{doc_id}_tbl_{i}",
                    "markdown": tbl_md,
                    "page_number": _prov_page(tbl)
                })
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

        # Docling locates figures but does not save them; save the PDF's embedded images
        # so the vision agent can read them, keeping Docling's captions where it found one.
        if os.path.splitext(filename)[1].lower() == ".pdf":
            saved = self._pdf_images(file_path, doc_id, filename)
            for v in saved:
                v.caption = page_captions.get(v.page_number, v.caption)
            visual_elements = saved or visual_elements

        return ParsedDocument(
            doc_id=doc_id,
            filename=filename,
            markdown_content=markdown_text,
            chunks=chunks,
            visual_elements=visual_elements,
            tables=tables
        )

    # ------------------------------------------------------------------
    # Fast mode (PyMuPDF / python-docx / plain text)
    # ------------------------------------------------------------------

    def _parse_with_pymupdf_fallback(self, file_path: str, doc_id: str, filename: str) -> ParsedDocument:
        """
        Fast structured parsing without Docling: PDF via PyMuPDF (section titles from font
        sizes, running headers/footers removed, de-hyphenation), DOCX via python-docx
        (heading styles and tables in document order), Markdown headings, plain text.
        """
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            blocks = self._pdf_blocks(file_path)
        elif ext == ".docx":
            blocks = self._docx_blocks(file_path)
        elif ext in TEXT_EXTENSIONS:
            blocks = self._text_blocks(file_path, markdown=ext in (".md", ".markdown"))
        else:
            blocks = self._unknown_blocks(file_path)

        chunks = chunk_blocks(doc_id, blocks, paged=(ext == ".pdf"))
        if not chunks:
            logger.warning(f"No extractable text found in {filename} (scanned or empty document?).")
        visual_elements = self._pdf_images(file_path, doc_id, filename) if ext == ".pdf" else []
        markdown = self._blocks_to_markdown(blocks)
        return ParsedDocument(
            doc_id=doc_id,
            filename=filename,
            markdown_content=markdown,
            chunks=chunks,
            visual_elements=visual_elements,
            tables=[]
        )

    def _pdf_images(self, file_path: str, doc_id: str, filename: str) -> List[VisualElement]:
        """
        Saves embedded figures (>= MIN_FIGURE_PX on both sides) to
        ``<images_dir>/<doc_id>/p<page>_img<k>.png`` and renders pages dominated by vector
        graphics (charts, diagrams) to ``p<page>_page.png``, so the vision agent can inspect
        the figures of a specific document. Failures never break ingestion.
        """
        elements: List[VisualElement] = []
        if not re.match(r"^[A-Za-z0-9_\-.]+$", doc_id or ""):
            return elements
        try:
            import fitz
            out_dir = os.path.join(self.images_dir, doc_id)
            seen = set()
            renders = 0
            with fitz.open(file_path) as doc:
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
                        elements.append(VisualElement(
                            figure_id=f"{doc_id}_p{page_no}_img{k}",
                            doc_id=doc_id,
                            page_number=page_no,
                            caption=f"Figure on page {page_no} of {filename}",
                            image_path=path,
                        ))
        except Exception as e:
            logger.warning(f"Figure extraction skipped for {filename}: {e}")
        return elements

    @staticmethod
    def _blocks_to_markdown(blocks: List[Tuple[int, str, str]]) -> str:
        parts, last_section = [], None
        for _, section, text in blocks:
            if section and section != last_section:
                parts.append(f"## {section}")
                last_section = section
            parts.append(text)
        return "\n\n".join(parts)

    def _pdf_blocks(self, file_path: str) -> List[Tuple[int, str, str]]:
        import fitz
        doc = fitz.open(file_path)
        flags = (fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_LIGATURES & ~fitz.TEXT_PRESERVE_IMAGES)
        pages = []
        size_weight: Counter = Counter()
        margin_counts: Counter = Counter()
        for page in doc:
            height = float(page.rect.height) or 1.0
            lines = []
            for b in page.get_text("dict", flags=flags).get("blocks", []):
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
                    block_lines.append({"text": text, "size": size, "bold": bool(bold), "margin": in_margin})
                if block_lines:
                    lines.append(block_lines)
            pages.append(lines)

        body = size_weight.most_common(1)[0][0] if size_weight else 10.0
        repeat_threshold = 2 if len(pages) <= 4 else 3
        blocks: List[Tuple[int, str, str]] = []
        section = ""
        for page_no, page_blocks in enumerate(pages, 1):
            if not page_blocks:
                logger.info(f"Page {page_no} has no extractable text (image-only page?).")
            for block_lines in page_blocks:
                para: List[str] = []
                heading: List[str] = []

                def flush_para():
                    if para:
                        blocks.append((page_no, section, _join_lines(para)))
                        para.clear()

                for ln in block_lines:
                    text = ln["text"]
                    if ln["margin"] and margin_counts[_margin_key(text)] >= repeat_threshold:
                        continue  # running header / footer / page number
                    is_heading = (
                        not ln["margin"]
                        and _looks_like_heading(text)
                        and (ln["size"] >= body * 1.18 or (ln["bold"] and ln["size"] >= body and len(text.split()) <= 8))
                    )
                    if is_heading:
                        flush_para()
                        heading.append(text)
                        continue
                    if heading:
                        section = " ".join(heading)[:120]
                        heading = []
                    para.append(text)
                if heading:
                    section = " ".join(heading)[:120]
                flush_para()
        return blocks

    @staticmethod
    def _docx_blocks(file_path: str) -> List[Tuple[int, str, str]]:
        blocks: List[Tuple[int, str, str]] = []
        try:
            import docx
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except Exception as e:
            logger.warning(f"python-docx unavailable ({e}); cannot parse {file_path} in fast mode.")
            return blocks
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
                rows = []
                for row in table.rows:
                    cells = []
                    for cell in row.cells:
                        ct = " ".join(cell.text.split())
                        if not cells or cells[-1] != ct:  # merged cells repeat their text
                            cells.append(ct)
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    blocks.append((1, section, "\n".join(rows)))
        return blocks

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

    def _text_blocks(self, file_path: str, markdown: bool = False) -> List[Tuple[int, str, str]]:
        text = self._read_text(file_path)
        blocks: List[Tuple[int, str, str]] = []
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

    def _unknown_blocks(self, file_path: str) -> List[Tuple[int, str, str]]:
        """Reads unknown formats only if they are actually text (never indexes binary noise)."""
        with open(file_path, "rb") as f:
            head = f.read(4096)
        if b"\x00" in head:
            logger.warning(f"Unsupported binary format for fast parsing: {file_path}")
            return []
        return self._text_blocks(file_path)


def _prov_page(item: Any) -> int:
    """Page number from a Docling item's provenance (1 if unknown)."""
    try:
        prov = getattr(item, "prov", None) or []
        return int(prov[0].page_no) if prov else 1
    except Exception:
        return 1


TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".log", ".yaml", ".yml", ".xml", ".html", ".htm", ".rst"}
CHUNK_MAX_WORDS = 300
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


def chunk_blocks(doc_id: str, blocks: List[Tuple[int, str, str]], paged: bool = True) -> List[RetrievedChunk]:
    """
    Packs (page, section, text) blocks into chunks of <= CHUNK_MAX_WORDS words without
    crossing page boundaries; a new section starts a new chunk once the current one has
    CHUNK_MIN_WORDS words; very long blocks are windowed with CHUNK_OVERLAP_WORDS overlap.
    """
    chunks: List[RetrievedChunk] = []
    counters: Dict[int, int] = {}
    cur_words: List[str] = []
    cur_page, cur_section = None, ""

    def emit():
        nonlocal cur_words
        if not cur_words:
            return
        k = counters.get(cur_page, 0)
        counters[cur_page] = k + 1
        chunks.append(RetrievedChunk(
            chunk_id=f"{doc_id}_p{cur_page}_c{k}",
            doc_id=doc_id,
            text=" ".join(cur_words),
            page_number=int(cur_page or 1),
            section_title=cur_section or (f"Page {cur_page}" if paged else "General"),
            score=0.0,
            retrieval_method="hybrid"
        ))
        cur_words = []

    for page, section, text in blocks:
        words = text.split()
        if not words:
            continue
        if cur_page is not None and page != cur_page:
            emit()
        elif section != cur_section and len(cur_words) >= CHUNK_MIN_WORDS:
            emit()
        if not cur_words:
            cur_page, cur_section = page, section
        if len(cur_words) + len(words) <= CHUNK_MAX_WORDS:
            cur_words.extend(words)
            continue
        if len(words) <= CHUNK_MAX_WORDS:
            emit()
            cur_page, cur_section = page, section
            cur_words = list(words)
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
            if start + CHUNK_MAX_WORDS >= len(words):
                break  # keep the last window open so short following blocks can join it
            emit()
            cur_page, cur_section = page, section
            start += step
    emit()
    return _merge_tiny(chunks)


def _merge_tiny(chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    """Folds fragments (< CHUNK_MIN_WORDS / 2 words) into the previous chunk of the same page."""
    out: List[RetrievedChunk] = []
    for ch in chunks:
        n = len(ch.text.split())
        if (out and n < CHUNK_MIN_WORDS // 2 and out[-1].page_number == ch.page_number
                and len(out[-1].text.split()) + n <= CHUNK_MAX_WORDS + CHUNK_OVERLAP_WORDS):
            out[-1] = out[-1].model_copy(update={"text": out[-1].text + " " + ch.text})
            continue
        out.append(ch)
    return out
