"""
Deterministic tests for the document-intelligence agents: OCR, the SQL table store and
table agent, sentence-level citation checking, citation highlighting and schema
extraction checks. No model calls (the table agent's model is replaced by a stub); the
OCR tests are skipped when Tesseract is not installed. Runs in a few seconds.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from parsing import ocr  # noqa: E402
from parsing.locate import align, best_sentence, locate  # noqa: E402
from retrieval.table_store import TableStore, parse_number  # noqa: E402
from guardrails.citation_checker import check_sentences, split_sentences, summarise  # noqa: E402
from agents.extraction_agent import dates_in, normalise_fields, quote_in_text, value_in_text  # noqa: E402

PLAN = [
    ["Wind turbines", "3,800,000", "5", "51%"],
    ["Concentrated solar plants", "49,000", "300", "20%"],
    ["Photovoltaic plants", "40,000", "300", "14%"],
    ["Rooftop PV systems", "1,700,000,000", "0.003", "6%"],
    ["Geothermal plants", "5,350", "100", "4%"],
    ["Hydroelectric plants", "900", "1,300", "4%"],
]
COLUMNS = ["Technology", "Units required", "Unit size (MW)", "Share of supply (%)"]


@pytest.fixture()
def store():
    s = TableStore(os.path.join(tempfile.mkdtemp(prefix="omnidoc-tables-"), "tables.db"))
    s.add_tables("doc_plan", [{"table_id": "doc_plan_t1", "page": 7, "bbox": [40, 100, 560, 380],
                               "title": "WWS plan", "columns": COLUMNS, "rows": PLAN, "source": "pdf"}])
    return s


# ---------------------------------------------------------------- table store
def test_table_store_types_columns_and_answers_selects(store):
    (table,) = store.tables_for(["doc_plan"])
    assert [c["type"] for c in table["columns"]] == ["TEXT", "REAL", "REAL", "REAL"]
    result = store.run_select(
        f'SELECT "technology" FROM "{table["table"]}" ORDER BY "unit_size_mw" DESC LIMIT 1', [table["table"]])
    assert result["rows"] == [["Hydroelectric plants"]]
    total = store.run_select(f'SELECT SUM("share_of_supply") FROM "{table["table"]}"', [table["table"]])
    assert total["rows"][0][0] == pytest.approx(99.0)


@pytest.mark.parametrize("sql", [
    'DROP TABLE "{t}"',
    'SELECT 1; DROP TABLE "{t}"',
    "SELECT * FROM table_catalog",
    "SELECT name FROM sqlite_master",
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "SELECT load_extension('evil')",
    "SELECT readfile('/etc/passwd')",
    "PRAGMA table_info(table_catalog)",
    "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) SELECT COUNT(*) FROM r",
])
def test_table_store_refuses_anything_but_bounded_reads(store, sql):
    table = store.tables_for(["doc_plan"])[0]["table"]
    with pytest.raises(ValueError):
        store.run_select(sql.format(t=table), [table], timeout_s=0.5)


@pytest.mark.parametrize("cell, expected", [
    ("3,800,000", 3800000.0), ("(12.5)", -12.5), ("51%", 51.0), ("₹ 1,200", 1200.0), (7, 7.0),
    ("n/a", None), ("Wind", None), (True, None),
])
def test_parse_number(cell, expected):
    assert parse_number(cell) == expected


def test_table_agent_runs_every_planned_query_and_adds_small_tables(store, monkeypatch):
    import agents.table_agent as table_agent
    table = store.tables_for(["doc_plan"])[0]["table"]
    plan = {"queries": [
        {"table": table, "sql": f'SELECT "technology" FROM "{table}" ORDER BY "unit_size_mw" DESC LIMIT 1',
         "answers": "largest unit size"},
        {"table": table, "sql": f'SELECT SUM("share_of_supply") AS solar FROM "{table}" WHERE "technology" LIKE \'%solar%\'',
         "answers": "solar share"},
    ]}
    monkeypatch.setattr(table_agent, "chat_json", lambda *a, **k: plan)
    results, detail = table_agent.TableQAAgent(store).answer(
        "Which technology has the largest unit size, and what share of supply comes from solar plants?", ["doc_plan"])
    assert [r["purpose"] for r in results] == ["largest unit size", "solar share", "all rows"]
    assert results[0]["rows"] == [["Hydroelectric plants"]]
    assert results[2]["row_count"] == len(PLAN)  # the whole small table, for the writer and the verifier
    assert results[0]["page"] == 7 and results[0]["bbox"] == [40, 100, 560, 380]


def test_table_agent_retries_a_failed_query_with_the_error(store, monkeypatch):
    import agents.table_agent as table_agent
    table = store.tables_for(["doc_plan"])[0]["table"]
    prompts = []
    plans = iter([{"sql": f'SELECT "no_such_column" FROM "{table}"'},
                  {"sql": f'SELECT COUNT(*) AS plants FROM "{table}"'}])
    monkeypatch.setattr(table_agent, "chat_json", lambda model, prompt, **k: prompts.append(prompt) or next(plans))
    results, _ = table_agent.TableQAAgent(store).answer("How many technologies does the plan table list?", ["doc_plan"])
    assert results[0]["rows"] == [[6]]
    assert "no such column" in prompts[1]


# ---------------------------------------------------------- citation checker
SOURCES = [
    {"n": 1, "kind": "chunk", "title": "Plan", "_text": "Wind supplies 51 percent of the demand from 3.8 million turbines."},
    {"n": 2, "kind": "chunk", "title": "Plan", "_text": "Water-related methods supply 9 percent of the demand."},
]


def test_split_sentences_keeps_offsets_lists_and_trailing_citations():
    answer = "## Mix\n- Wind supplies 51% [1].\n- Water adds 9%. [2]\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    sentences = split_sentences(answer)
    assert [s["citations"] for s in sentences] == [[1], [2]]
    for s in sentences:
        assert answer[s["start"]:s["end"]] == s["text"]


def test_check_sentences_moves_a_wrong_citation_and_flags_unknown_figures():
    answer = "Wind supplies 51% of demand [1]. Water supplies 9% of demand [1]. Coal supplies 30% [2]."
    judge = lambda prompt: {"sentences": [  # noqa: E731
        {"id": "S1", "verdict": "supported", "supported_by": [1]},
        {"id": "S2", "verdict": "supported", "supported_by": [2]},
        {"id": "S3", "verdict": "supported", "supported_by": [2]},
    ]}
    checks, corrected = check_sentences(answer, "What supplies the demand?", SOURCES, judge=judge)
    assert [c["verdict"] for c in checks] == ["supported", "supported", "unsupported"]
    assert checks[1]["corrected_to"] == [2]
    assert "Water supplies 9% of demand [2]." in corrected
    assert "30%" in checks[2]["reason"]
    for c in checks:  # offsets point into the corrected answer
        assert corrected[c["start"]:c["end"]] == c["text"]
    counts = summarise(checks)
    assert counts["unsupported"] == 1 and counts["corrected"] == 1


def test_check_sentences_without_a_judge_still_checks_figures():
    checks, _ = check_sentences("Wind supplies 51% [1].", "q", SOURCES, judge=None)
    assert checks[0]["verdict"] == "unchecked" and "corrected_to" not in checks[0]


# ------------------------------------------------------------------- locate
def _pdf(lines):
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 72
    for text in lines:
        page.insert_text((72, y), text, fontsize=11)
        y += 18
    return doc


def test_best_sentence_splits_after_brackets_but_not_abbreviations():
    passage = ("(Other mixes could work.) Wind supplies 51 percent of the demand. "
               "Power use is 12.5 TW according to the U.S. Energy Information Administration.")
    assert best_sentence(passage, "Wind would supply 51% of demand").startswith("Wind supplies 51 percent")
    assert best_sentence(passage, "12.5 TW of power is used").endswith("Energy Information Administration.")


def test_locate_highlights_the_supporting_sentence_line_by_line():
    lines = ["The plan needs no new nuclear plants.", "Wind supplies 51 percent of the demand, provided by",
             "3.8 million large wind turbines worldwide.", "Solar supplies most of the rest."]
    doc = _pdf(lines)
    passage = " ".join(lines)
    res = locate(doc, {}, 1, passage=passage, claim="Wind would supply 51% of demand from 3.8 million turbines [2].")
    assert res["method"] == "sentence"
    assert len(res["rects"]) == 2  # one rectangle per line of the sentence
    top, bottom = res["rects"][0][1], res["rects"][-1][3]
    assert 0.08 < top < 0.12 and bottom < 0.15  # lines two and three, not the whole passage
    assert all(0.0 <= v <= 1.0 for r in res["rects"] for v in r)


def test_locate_falls_back_to_passage_boxes_then_page():
    doc = _pdf(["Nothing related is written here."])
    layout = {"chunks": {"doc_c0": [[1, 72, 60, 300, 80]]}}
    res = locate(doc, layout, 1, passage="Nothing related is written here.", claim="Totally different claim", chunk_id="doc_c0")
    assert res["method"] == "passage" and len(res["rects"]) == 1
    assert locate(doc, {}, 1, passage="", claim="")["method"] == "page"
    table = locate(doc, {}, 1, table=[1, 50, 100, 500, 300])
    assert table["method"] == "table" and table["rects"][0][0] == pytest.approx((50 - 1.5) / 595, abs=1e-4)


def test_locate_exact_quotes_and_follows_a_passage_onto_the_next_page():
    import fitz
    doc = fitz.open()
    for text in ("First page text about turbines.", "Total Due: INR 991,200"):
        doc.new_page(width=595, height=842).insert_text((72, 72), text, fontsize=11)
    layout = {"chunks": {"doc_c0": [[1, 72, 60, 300, 80], [2, 72, 60, 300, 80]]}}
    res = locate(doc, layout, 1, passage="First page text about turbines. Total Due: INR 991,200",
                 claim="Total Due: INR 991,200", chunk_id="doc_c0", exact=True)
    assert res["page"] == 2 and res["method"] == "sentence"


def test_align_reports_coverage():
    words = [[0, 0, 10, 10, w] for w in "the quick brown fox jumps".split()]
    rects, coverage = align("quick brown fox", words)
    assert coverage == 1.0 and len(rects) == 1
    assert align("completely unrelated", words)[1] == 0.0


# ---------------------------------------------------------------- extraction
def test_quote_and_value_checks():
    text = "TAX INVOICE Invoice No: NW-2026-0419 Invoice Date: 12 August 2026 Total Due: INR 991,200"
    assert quote_in_text("Invoice No: NW-2026-0419", text)
    assert not quote_in_text("Invoice No: AB-1111", text)
    assert value_in_text(991200, "number", text)
    assert value_in_text("2026-08-12", "date", text)
    assert not value_in_text("2026-08-13", "date", text)
    assert dates_in("on August 12, 2026") == {(2026, 8, 12)}
    assert value_in_text(["NW-2026-0419"], "list", text)


def test_normalise_fields_cleans_names_and_types():
    fields = normalise_fields([{"label": "Invoice number", "type": "text"}, {"label": "Invoice number"},
                               {"name": "Total", "type": "money"}, {"label": ""}])
    assert [(f["name"], f["type"]) for f in fields] == [("invoice_number", "text"), ("total", "text")]


# ---------------------------------------------------------------------- OCR
needs_tesseract = pytest.mark.skipif(not ocr.tesseract_available(), reason="Tesseract is not installed")


def _text_image(path, rotate=0):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 500), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    for i, line in enumerate(["Invoice No: NW-2026-0419", "Total Due: INR 991,200", "Payment within 30 days"]):
        draw.text((60, 60 + i * 120), line, fill="black", font=font)
    if rotate:
        img = img.rotate(rotate, expand=True, fillcolor="white")
    img.save(path)
    return path


@needs_tesseract
@pytest.mark.parametrize("rotate", [0, 90])
def test_ocr_reads_images_and_maps_words_to_page_coordinates(rotate):
    path = _text_image(os.path.join(tempfile.mkdtemp(), "scan.png"), rotate)
    with ocr.open_as_pdf(path) as doc:
        page = doc[0]
        assert ocr.page_needs_ocr(page, 0)
        result = ocr.ocr_page(page)
        width, height = page.rect.width, page.rect.height
    text = " ".join(w[4] for w in result["words"])
    assert "NW-2026-0419" in text and "991,200" in text
    assert result["rotation"] == rotate % 360 or rotate == 0
    for x0, y0, x1, y1, _ in result["words"]:
        assert 0 <= x0 < x1 <= width + 1 and 0 <= y0 < y1 <= height + 1


@needs_tesseract
def test_scanned_image_is_parsed_into_chunks_with_layout():
    from parsing.docling_parser import DoclingParser
    path = _text_image(os.path.join(tempfile.mkdtemp(), "invoice.png"))
    parsed = DoclingParser(extracted_images_dir=tempfile.mkdtemp()).parse_document(path, doc_id="doc_scan", fast_mode=True)
    assert parsed.ocr_pages == [1]
    assert "991,200" in " ".join(c.text for c in parsed.chunks)
    assert parsed.layout["pages"][0]["ocr"] and parsed.layout["ocr_words"]["1"]
    assert all(v.caption.endswith("(scanned)") for v in parsed.visual_elements)
