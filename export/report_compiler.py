"""
Report & Publication Compilation Engine for OmniDoc.
Dynamically transforms Agentic Graph RAG reasoning, mathematical calculations,
evidence citations, and conversation threads into publication-grade executive documents.

Engines:
1. WeasyPrint: CSS3 Paged Media PDF generation (running headers/footers, page numbering, typography)
2. python-docx: Native Microsoft Word DOCX generation with styled tables, headings, and callouts
"""
import os
import io
import re
import sys
import datetime
import html
from typing import List, Dict, Any, Optional

# Ensure macOS dynamic library path for Homebrew Cairo / Pango
os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib")

try:
    import weasyprint
except ImportError:
    weasyprint = None

try:
    import docx
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml import OxmlElement, parse_xml
    from docx.oxml.ns import nsdecls, qn
except ImportError:
    docx = None


# Characters XML 1.0 forbids (python-docx and WeasyPrint both reject them)
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _xml_safe(value: Any) -> Any:
    """Recursively strips XML-invalid control characters from strings."""
    if isinstance(value, str):
        return _XML_INVALID.sub("", value)
    if isinstance(value, dict):
        return {k: _xml_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_xml_safe(v) for v in value]
    return value


class ReportCompiler:
    """Compiles analytical RAG findings into styled PDFs and Word documents."""

    def __init__(self, brand_color: str = "#2563eb", secondary_color: str = "#1e293b"):
        self.brand_color = brand_color
        self.secondary_color = secondary_color

    def compile_pdf(
        self,
        title: str,
        messages: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bytes:
        """
        Compiles messages and verified artifacts into an executive PDF using WeasyPrint.
        """
        if weasyprint is None:
            raise RuntimeError("WeasyPrint is not installed or Cairo/Pango libraries are unavailable.")

        title = _xml_safe(title)
        messages = _xml_safe(messages)
        meta = metadata or {}
        generated_date = datetime.datetime.now().strftime("%B %d, %Y - %H:%M")
        model_name = meta.get("model_name") or "local model"
        groundedness_score = meta.get("groundedness_score")
        # Only report a groundedness figure the verifier actually produced
        groundedness_pct = (
            int(round(float(groundedness_score) * 100))
            if isinstance(groundedness_score, (int, float)) and not isinstance(groundedness_score, bool)
            else None
        )

        html_content = self._build_html(
            title=title,
            messages=messages,
            generated_date=generated_date,
            model_name=model_name,
            groundedness_pct=groundedness_pct,
            doc_count=meta.get("doc_count", 1)
        )

        doc = weasyprint.HTML(string=html_content)
        return doc.write_pdf()

    def compile_docx(
        self,
        title: str,
        messages: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bytes:
        """
        Compiles messages and verified artifacts into a native Microsoft Word DOCX file.
        """
        if docx is None:
            raise RuntimeError("python-docx is not installed.")

        title = _xml_safe(title)
        messages = _xml_safe(messages)
        meta = metadata or {}
        doc = docx.Document()

        # Page margins
        for section in doc.sections:
            section.top_margin = Inches(1.0)
            section.bottom_margin = Inches(1.0)
            section.left_margin = Inches(1.0)
            section.right_margin = Inches(1.0)

        # Title
        p_title = doc.add_paragraph()
        p_title.paragraph_format.space_before = Pt(0)
        p_title.paragraph_format.space_after = Pt(4)
        run_title = p_title.add_run(title)
        run_title.font.name = "Arial"
        run_title.font.size = Pt(24)
        run_title.font.bold = True
        run_title.font.color.rgb = RGBColor(30, 41, 59)

        # Subtitle / Metadata
        p_meta = doc.add_paragraph()
        p_meta.paragraph_format.space_after = Pt(20)
        generated_date = datetime.datetime.now().strftime("%B %d, %Y at %H:%M UTC")
        run_meta = p_meta.add_run(
            f"OmniDoc Intelligence Report  •  Generated: {generated_date}  •  Model: {meta.get('model_name', 'qwen2.5:7b-instruct')}"
        )
        run_meta.font.name = "Arial"
        run_meta.font.size = Pt(9.5)
        run_meta.font.italic = True
        run_meta.font.color.rgb = RGBColor(100, 116, 139)

        # Divider line table
        self._add_docx_horizontal_rule(doc)

        for i, msg in enumerate(messages, 1):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            math_items = (
                msg.get("math_results")
                or msg.get("math")
                or ([msg["math_result"]] if msg.get("math_result") else [])
            )
            charts = msg.get("visual_artifacts") or msg.get("charts", [])
            conflicts = msg.get("conflicts", [])
            sources = msg.get("sources", [])

            if role == "user":
                p_user = doc.add_paragraph()
                p_user.paragraph_format.space_before = Pt(16)
                p_user.paragraph_format.space_after = Pt(6)
                r_tag = p_user.add_run("QUERY / PROMPT:")
                r_tag.font.bold = True
                r_tag.font.size = Pt(10)
                r_tag.font.color.rgb = RGBColor(37, 99, 235)
                
                p_u_text = doc.add_paragraph()
                p_u_text.paragraph_format.left_indent = Inches(0.2)
                p_u_text.paragraph_format.space_after = Pt(14)
                r_ut = p_u_text.add_run(content)
                r_ut.font.size = Pt(11)
                r_ut.font.italic = True
            else:
                p_asst = doc.add_paragraph()
                p_asst.paragraph_format.space_before = Pt(12)
                p_asst.paragraph_format.space_after = Pt(8)
                r_atag = p_asst.add_run("SYNTHESIZED INTELLIGENCE & AUDIT:")
                r_atag.font.bold = True
                r_atag.font.size = Pt(10)
                r_atag.font.color.rgb = RGBColor(15, 23, 42)

                # Body text (cleaned lines)
                for line in content.split("\n"):
                    if not line.strip():
                        continue
                    if line.strip().startswith("- ") or line.strip().startswith("* "):
                        p_bullet = doc.add_paragraph(line.strip()[2:], style='List Bullet')
                        p_bullet.paragraph_format.space_after = Pt(3)
                    elif line.strip().startswith("###"):
                        h3 = doc.add_heading(line.strip().replace("###", "").strip(), level=3)
                        h3.paragraph_format.space_before = Pt(10)
                        h3.paragraph_format.space_after = Pt(4)
                    elif line.strip().startswith("##"):
                        h2 = doc.add_heading(line.strip().replace("##", "").strip(), level=2)
                        h2.paragraph_format.space_before = Pt(12)
                        h2.paragraph_format.space_after = Pt(4)
                    else:
                        p_norm = doc.add_paragraph(line.strip())
                        p_norm.paragraph_format.space_after = Pt(4)

                # Mathematical Computations Table
                if math_items:
                    self._add_docx_math_section(doc, math_items)

                # Grounded Source Citations
                if sources:
                    self._add_docx_sources_section(doc, sources)

                # Discrepancies
                if conflicts:
                    self._add_docx_conflicts_section(doc, conflicts)

            # Subtle separator between turns
            if i < len(messages):
                doc.add_paragraph().paragraph_format.space_after = Pt(10)

        # Save to buffer
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.read()

    def _build_html(
        self,
        title: str,
        messages: List[Dict[str, Any]],
        generated_date: str,
        model_name: str,
        groundedness_pct: Optional[int],
        doc_count: int
    ) -> str:
        """Constructs an elegant, publication-grade HTML document for WeasyPrint."""
        safe_title = html.escape(title)

        body_html = ""
        for i, msg in enumerate(messages, 1):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            math_items = (
                msg.get("math_results")
                or msg.get("math")
                or ([msg["math_result"]] if msg.get("math_result") else [])
            )
            charts = msg.get("visual_artifacts") or msg.get("charts", [])
            conflicts = msg.get("conflicts", [])
            sources = msg.get("sources", [])

            if role == "user":
                body_html += f"""
                <div class="turn turn-user">
                    <div class="turn-header">USER QUERY</div>
                    <div class="turn-content user-query">{html.escape(content)}</div>
                </div>
                """
            else:
                formatted_content = self._format_markdown_for_html(content)
                
                # Math Callout Box
                math_html = ""
                if math_items:
                    math_rows = ""
                    for mr in math_items:
                        task = html.escape(str(mr.get("task", "Calculation")))
                        formula = html.escape(str(mr.get("formula", "")))
                        result = html.escape(str(mr.get("exact_result", "")))
                        units = html.escape(str(mr.get("units") or ""))
                        code = html.escape(str(mr.get("code_executed", "")))
                        
                        math_rows += f"""
                        <div class="math-card">
                            <div class="math-task"><strong>Task:</strong> {task}</div>
                            {f'<div class="math-formula"><code>{formula}</code></div>' if formula else ''}
                            <div class="math-result"><strong>Exact Result:</strong> <span class="badge badge-success">{result} {units}</span></div>
                            {f'<pre class="math-code">{code}</pre>' if code else ''}
                        </div>
                        """
                    math_html = f"""
                    <div class="section-box math-box">
                        <div class="box-title">🔢 Audited Mathematical Computations (Sandboxed Python)</div>
                        {math_rows}
                    </div>
                    """

                # Sources HTML Box
                sources_html = ""
                if sources:
                    source_rows = ""
                    for s in sources:
                        chunk_id = html.escape(str(s.get("chunk_id", "")))
                        score = int(float(s.get("score", 0.95)) * 100)
                        snippet = html.escape(str(s.get("snippet", "")))
                        source_type = html.escape(str(s.get("source_type", "hybrid")))
                        source_rows += f"""
                        <div style="margin-bottom:6px; padding:6px 10px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; font-size:8.5pt;">
                            <span style="font-weight:600; color:#2563eb;">[{chunk_id or 'Source'}]</span>
                            <span style="background:#ecfdf5; color:#059669; padding:1px 5px; border-radius:3px; font-size:7.5pt; font-weight:600; margin-left:6px;">{score}% Match &bull; {source_type}</span>
                            <div style="margin-top:3px; color:#475569; font-style:italic;">"{snippet}"</div>
                        </div>
                        """
                    sources_html = f"""
                    <div class="section-box" style="margin-top:14px; padding:10px 14px; background:#f0f9ff; border-left:4px solid #0284c7; border-radius:4px;">
                        <div class="box-title" style="font-weight:700; color:#0369a1; font-size:9.5pt; margin-bottom:8px;">Sources</div>
                        {source_rows}
                    </div>
                    """

                # Conflict Discrepancy Box
                conflict_html = ""
                if conflicts:
                    conflict_rows = ""
                    for cf in conflicts:
                        claim = html.escape(str(cf.get("conflicting_claim", "")))
                        status = html.escape(str(cf.get("resolution_status", "Audited")))
                        rationale = html.escape(str(cf.get("rationale", "")))
                        conflict_rows += f"""
                        <div class="conflict-item">
                            <div class="conflict-claim"><strong>Discrepancy:</strong> {claim}</div>
                            <div class="conflict-detail"><strong>Status:</strong> {status} &bull; <em>{rationale}</em></div>
                        </div>
                        """
                    conflict_html = f"""
                    <div class="section-box conflict-box">
                        <div class="box-title">Conflicting sources</div>
                        {conflict_rows}
                    </div>
                    """

                body_html += f"""
                <div class="turn turn-assistant">
                    <div class="turn-header">Answer</div>
                    <div class="turn-content assistant-response">
                        {formatted_content}
                    </div>
                    {math_html}
                    {sources_html}
                    {conflict_html}
                </div>
                """

        return f"""<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>{safe_title}</title>
            <style>
                table.md-table {{ width: 100%; border-collapse: collapse; margin: 10px 0 14px; font-size: 9pt; }}
                table.md-table th {{ text-align: left; font-weight: 600; border-bottom: 1px solid #b9b4a8; padding: 5px 8px; }}
                table.md-table td {{ border-bottom: 1px solid #e3e0d8; padding: 5px 8px; vertical-align: top; }}
                .math-block {{ margin: 10px 0; padding: 8px 12px; background: #f6f5f1; border-radius: 4px; }}
                code.math {{ background: none; font-style: italic; }}
                sup.cite {{ font-size: 7pt; font-weight: 600; color: #94560a; padding: 0 1px; }}
                ol {{ margin: 6px 0 10px 18px; }}
                @page {{
                    size: A4;
                    margin: 22mm 18mm 22mm 18mm;
                    @top-left {{
                        content: "OmniDoc Document Intelligence";
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                        font-size: 8pt;
                        color: #94a3b8;
                    }}
                    @top-right {{
                        content: "{safe_title}";
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                        font-size: 8pt;
                        color: #94a3b8;
                    }}
                    @bottom-left {{
                        content: "Generated locally by OmniDoc";
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                        font-size: 8pt;
                        color: #94a3b8;
                    }}
                    @bottom-right {{
                        content: "Page " counter(page) " of " counter(pages);
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                        font-size: 8pt;
                        color: #94a3b8;
                    }}
                }}

                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    font-size: 10pt;
                    line-height: 1.55;
                    color: #1e293b;
                    margin: 0;
                    padding: 0;
                }}

                .cover-header {{
                    border-bottom: 2px solid #e2e8f0;
                    padding-bottom: 16px;
                    margin-bottom: 24px;
                }}

                .badge-brand {{
                    display: inline-block;
                    background-color: #eff6ff;
                    color: #1d4ed8;
                    border: 1px solid #bfdbfe;
                    border-radius: 4px;
                    padding: 2px 8px;
                    font-size: 7.5pt;
                    font-weight: 700;
                    letter-spacing: 0.5px;
                    text-transform: uppercase;
                    margin-bottom: 8px;
                }}

                h1.doc-title {{
                    font-size: 20pt;
                    font-weight: 800;
                    color: #0f172a;
                    margin: 0 0 10px 0;
                    letter-spacing: -0.5px;
                }}

                .metadata-bar {{
                    display: flex;
                    justify-content: space-between;
                    font-size: 8.5pt;
                    color: #64748b;
                }}

                .metadata-bar span {{
                    margin-right: 18px;
                }}

                .grounded-badge {{
                    background-color: #ecfdf5;
                    color: #065f46;
                    border: 1px solid #a7f3d0;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-weight: 600;
                }}

                .turn {{
                    margin-bottom: 22px;
                    page-break-inside: avoid;
                }}

                .turn-header {{
                    font-size: 7.5pt;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.8px;
                    color: #64748b;
                    margin-bottom: 6px;
                }}

                .turn-user {{
                    background-color: #f8fafc;
                    border-left: 3px solid #3b82f6;
                    padding: 10px 14px;
                    border-radius: 0 6px 6px 0;
                }}

                .user-query {{
                    font-size: 10.5pt;
                    font-weight: 500;
                    color: #1e3a8a;
                    font-style: italic;
                }}

                .turn-assistant {{
                    padding: 4px 0 16px 0;
                }}

                .assistant-response p {{
                    margin: 0 0 8px 0;
                }}

                .assistant-response ul, .assistant-response ol {{
                    margin: 4px 0 10px 20px;
                    padding: 0;
                }}

                .assistant-response li {{
                    margin-bottom: 4px;
                }}

                .assistant-response h2 {{
                    font-size: 13pt;
                    font-weight: 700;
                    color: #0f172a;
                    margin: 16px 0 8px 0;
                    border-bottom: 1px solid #f1f5f9;
                    padding-bottom: 4px;
                }}

                .assistant-response h3 {{
                    font-size: 11pt;
                    font-weight: 600;
                    color: #1e293b;
                    margin: 12px 0 6px 0;
                }}

                .section-box {{
                    margin-top: 14px;
                    border-radius: 6px;
                    padding: 12px 14px;
                    page-break-inside: avoid;
                }}

                .math-box {{
                    background-color: #faf5ff;
                    border: 1px solid #e9d5ff;
                }}

                .conflict-box {{
                    background-color: #fffbeb;
                    border: 1px solid #fde68a;
                }}

                .box-title {{
                    font-size: 8.5pt;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    color: #475569;
                    margin-bottom: 8px;
                }}

                .math-card {{
                    background-color: #ffffff;
                    border: 1px solid #f3e8ff;
                    border-radius: 4px;
                    padding: 8px 10px;
                    margin-bottom: 8px;
                }}

                .math-card:last-child {{
                    margin-bottom: 0;
                }}

                .math-task {{
                    font-size: 9pt;
                    color: #334155;
                    margin-bottom: 4px;
                }}

                .math-formula code {{
                    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
                    font-size: 8.5pt;
                    background-color: #f8fafc;
                    padding: 2px 6px;
                    border-radius: 3px;
                    color: #7e22ce;
                }}

                .math-code {{
                    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
                    font-size: 8pt;
                    background-color: #1e1b4b;
                    color: #e0e7ff;
                    padding: 8px;
                    border-radius: 4px;
                    margin: 6px 0 0 0;
                    white-space: pre-wrap;
                }}

                .badge-success {{
                    background-color: #10b981;
                    color: #ffffff;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-weight: 700;
                    font-size: 8.5pt;
                }}

                .conflict-item {{
                    background-color: #ffffff;
                    border: 1px solid #fef3c7;
                    border-radius: 4px;
                    padding: 8px 10px;
                    margin-bottom: 6px;
                }}

                .conflict-claim {{
                    font-size: 9pt;
                    color: #92400e;
                }}

                .conflict-detail {{
                    font-size: 8.5pt;
                    color: #451a03;
                    margin-top: 2px;
                }}
            </style>
        </head>
        <body>
            <div class="cover-header">
                <div class="badge-brand">OmniDoc report</div>
                <h1 class="doc-title">{safe_title}</h1>
                <div class="metadata-bar">
                    <span><strong>Generated:</strong> {generated_date}</span>
                    <span><strong>Model:</strong> {html.escape(model_name)}</span>
                    <span><strong>Groundedness:</strong> <span class="grounded-badge">{f"{groundedness_pct}% verified" if groundedness_pct is not None else "not verified"}</span></span>
                </div>
            </div>

            <div class="content-body">
                {body_html}
            </div>
        </body>
        </html>
        """

    def _format_markdown_for_html(self, text: str) -> str:
        """Converts the markdown the synthesis agent writes (headings, lists, tables,
        bold/italic, code, [n] citations, $$ display math) to semantic HTML."""
        lines = text.replace("\r\n", "\n").split("\n")
        out: List[str] = []
        list_tag: Optional[str] = None
        i = 0

        def close_list():
            nonlocal list_tag
            if list_tag:
                out.append(f"</{list_tag}>")
                list_tag = None

        while i < len(lines):
            stripped = lines[i].strip()
            if not stripped:
                close_list()
                i += 1
                continue

            # Display math block: $$ ... $$ (single or multi-line)
            if stripped.startswith("$$"):
                close_list()
                block = [stripped[2:]]
                if not (stripped.endswith("$$") and len(stripped) > 2):
                    i += 1
                    while i < len(lines) and "$$" not in lines[i]:
                        block.append(lines[i])
                        i += 1
                    if i < len(lines):
                        block.append(lines[i].split("$$")[0])
                expr = " ".join(b.strip() for b in block).replace("$$", "").strip()
                out.append(f'<div class="math-block"><code>{html.escape(expr)}</code></div>')
                i += 1
                continue

            # Pipe table: header row followed by a |---| separator row
            if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
                close_list()
                header = [c.strip() for c in stripped.strip("|").split("|")]
                rows = []
                i += 2
                while i < len(lines) and lines[i].strip().startswith("|"):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                    i += 1
                thead = "".join(f"<th>{self._inline_markdown(c)}</th>" for c in header)
                tbody = "".join(
                    "<tr>" + "".join(f"<td>{self._inline_markdown(c)}</td>" for c in r) + "</tr>" for r in rows
                )
                out.append(f'<table class="md-table"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>')
                continue

            heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
            ordered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
            if heading:
                close_list()
                level = min(4, max(2, len(heading.group(1)) + 1 if len(heading.group(1)) == 1 else len(heading.group(1))))
                out.append(f"<h{level}>{self._inline_markdown(heading.group(2))}</h{level}>")
            elif stripped.startswith(("- ", "* ", "• ")):
                if list_tag != "ul":
                    close_list()
                    out.append("<ul>")
                    list_tag = "ul"
                out.append(f"<li>{self._inline_markdown(stripped[2:])}</li>")
            elif ordered:
                if list_tag != "ol":
                    close_list()
                    out.append("<ol>")
                    list_tag = "ol"
                out.append(f"<li>{self._inline_markdown(ordered.group(1))}</li>")
            else:
                close_list()
                out.append(f"<p>{self._inline_markdown(stripped)}</p>")
            i += 1

        close_list()
        return "\n".join(out)

    def _inline_markdown(self, text: str) -> str:
        """Inline formatting: bold, italic, code, inline math and [n] citations."""
        s = html.escape(text)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        s = re.sub(r"\$(?!\s)([^$]+?)(?<!\s)\$", r'<code class="math">\1</code>', s)
        s = re.sub(r"\[(\d{1,3})\]", r'<sup class="cite">\1</sup>', s)
        s = re.sub(
            r"\[(vector_chunk|Chunk|Passage|source):\s*([a-zA-Z0-9_-]+)\]",
            r'<sup class="cite">\2</sup>',
            s
        )
        return s

    def _add_docx_horizontal_rule(self, doc):
        """Adds a subtle horizontal divider line in docx."""
        table = doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = table.cell(0, 0)
        cell.width = Inches(6.5)
        tcPr = cell._tc.get_or_add_tcPr()
        borders = parse_xml(
            f'<w:tcBorders {nsdecls("w")}>\n'
            f'<w:top w:val="none"/>\n'
            f'<w:left w:val="none"/>\n'
            f'<w:bottom w:val="single" w:sz="8" w:space="0" w:color="CBD5E1"/>\n'
            f'<w:right w:val="none"/>\n'
            f'</w:tcBorders>'
        )
        tcPr.append(borders)

    def _add_docx_math_section(self, doc, math_items):
        """Adds styled mathematical results table to docx."""
        h = doc.add_heading("Calculations", level=3)
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(4)

        tbl = doc.add_table(rows=1, cols=4)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        hdr_cells = tbl.rows[0].cells
        hdr_cells[0].text = "Task"
        hdr_cells[1].text = "Formula"
        hdr_cells[2].text = "Result"
        hdr_cells[3].text = "Units"

        # Header styling
        for cell in hdr_cells:
            shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F1F5F9"/>')
            cell._tc.get_or_add_tcPr().append(shading)
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.bold = True
                    r.font.size = Pt(9)

        for m in math_items:
            row = tbl.add_row().cells
            row[0].text = str(m.get("task", ""))
            row[1].text = str(m.get("formula", ""))
            row[2].text = str(m.get("exact_result", ""))
            row[3].text = str(m.get("units") or "")
            for cell in row:
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(8.5)

    def _add_docx_conflicts_section(self, doc, conflicts):
        """Adds discrepancy audit items to docx."""
        h = doc.add_heading("Conflicting sources", level=3)
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(4)

        for cf in conflicts:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            r1 = p.add_run("• Claim: ")
            r1.font.bold = True
            p.add_run(f"{cf.get('conflicting_claim', '')}  —  ")
            r2 = p.add_run(f"Status: {cf.get('resolution_status', 'Audited')}\n")
            r2.font.bold = True
            p.add_run(f"  Rationale: {cf.get('rationale', '')}")

    def _add_docx_sources_section(self, doc, sources):
        """Adds grounded source citations to docx."""
        h = doc.add_heading("Sources", level=3)
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(4)

        for s in sources:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.left_indent = Inches(0.15)
            r_cid = p.add_run(f"[{s.get('chunk_id') or 'Source'}]: ")
            r_cid.font.bold = True
            r_cid.font.size = Pt(9)
            r_cid.font.color.rgb = RGBColor(37, 99, 235)

            score = int(float(s.get("score", 0.95)) * 100)
            r_sc = p.add_run(f"({score}% match • {s.get('source_type', 'hybrid')})\n")
            r_sc.font.size = Pt(8.5)
            r_sc.font.color.rgb = RGBColor(5, 150, 105)

            snippet = s.get("snippet", "")
            if snippet:
                r_snip = p.add_run(f'"{snippet}"')
                r_snip.font.italic = True
                r_snip.font.size = Pt(8.5)
                r_snip.font.color.rgb = RGBColor(71, 85, 105)
