"""
Integration tests for the document viewer, summary and extraction endpoints: uploads a
generated PDF, a CSV and (with Tesseract) a scanned image, then reads page images,
citation highlights, text and tables. Runs against a throwaway data directory. Uploads
embed text with Ollama, so the module is skipped when Ollama is not running; background
summaries and graph extraction are switched off so no other model calls are made.
"""
import os
import sys
import tempfile

os.environ.setdefault("OMNIDOC_DATA_DIR", tempfile.mkdtemp(prefix="omnidoc-viewer-test-"))
os.environ["OMNIDOC_WARMUP"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import core.pipeline  # noqa: E402
from parsing import ocr  # noqa: E402
from server import app, ollama_models  # noqa: E402

pytestmark = pytest.mark.skipif(ollama_models(timeout=1.5) is None, reason="Ollama is not running (uploads embed text)")

client = TestClient(app)

LINES = [
    "The Plan: Power Plants Required",
    "Clearly, enough renewable energy exists to power the world.",
    "Wind supplies 51 percent of the demand, provided by 3.8 million large",
    "wind turbines worldwide. Another 40 percent comes from photovoltaics.",
]


@pytest.fixture(autouse=True)
def no_background_models(monkeypatch):
    monkeypatch.setattr(core.pipeline, "SUMMARIES_ENABLED", False)
    monkeypatch.setattr(core.pipeline, "GRAPH_CHUNK_LIMIT", 0)
    monkeypatch.setattr(core.pipeline, "AUTO_EXTRACT", False)


def _pdf_bytes() -> bytes:
    import fitz
    doc = fitz.open()
    for p in range(2):
        page = doc.new_page(width=595, height=842)
        y = 72
        for text in (LINES if p == 1 else ["An introduction to the energy plan, with no figures."]):
            page.insert_text((72, y), text, fontsize=11)
            y += 18
    return doc.tobytes()


def _upload(name: str, data: bytes, mime: str) -> dict:
    resp = client.post("/api/documents/upload", files={"file": (name, data, mime)})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_pdf_pages_highlights_and_text():
    doc = _upload("plan.pdf", _pdf_bytes(), "application/pdf")
    doc_id = doc["doc_id"]
    listed = {d["id"]: d for d in client.get("/api/documents").json()["documents"]}[doc_id]
    assert listed["pages"] == 2 and listed["viewer"] == "pages" and listed["ocr_pages"] == 0

    info = client.get(f"/api/documents/{doc_id}/info").json()
    assert info["file_type"] == "pdf" and len(info["pages"]) == 2 and info["pages"][0]["w"] == 595

    page = client.get(f"/api/documents/{doc_id}/pages/2?width=700")
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert page.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/documents/{doc_id}/pages/9").status_code == 404

    text = client.get(f"/api/documents/{doc_id}/text").json()
    cited = next(c for c in text["chunks"] if "51 percent" in c["text"])
    loc = client.post(f"/api/documents/{doc_id}/locate", json={
        "chunk_id": cited["chunk_id"], "page": cited["page"],
        "claim": "Wind would supply 51% of demand from 3.8 million turbines [1].",
    }).json()
    assert loc["page"] == 2 and loc["method"] == "sentence" and loc["chunk_id"] == cited["chunk_id"]
    assert len(loc["rects"]) == 2 and all(0 <= v <= 1 for r in loc["rects"] for v in r)
    assert loc["quote"].startswith("Wind supplies 51 percent")

    original = client.get(f"/api/documents/{doc_id}/file")
    assert original.status_code == 200 and original.headers["content-type"] == "application/pdf"
    assert original.headers["content-disposition"].startswith("inline")

    summary = client.get(f"/api/documents/{doc_id}/summary").json()
    assert summary["status"] == "missing" and summary["summary"] is None

    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}/info").status_code == 404


def test_spreadsheet_tables_and_text_highlights():
    csv = "Technology,Units required,Share of supply (%)\nWind turbines,\"3,800,000\",51\nHydroelectric plants,900,4\n"
    doc = _upload("plan.csv", csv.encode(), "text/csv")
    assert doc["table_count"] == 1
    doc_id = doc["doc_id"]
    info = client.get(f"/api/documents/{doc_id}/info").json()
    assert info["viewer"] == "text" and info["pages"] == []
    (table,) = info["tables"]
    data = client.get(f"/api/documents/{doc_id}/tables/{table['table']}").json()
    assert data["columns"] == ["Technology", "Units required", "Share of supply (%)"]
    assert data["rows"][0] == ["Wind turbines", 3800000.0, 51.0]
    assert client.get(f"/api/documents/{doc_id}/tables/t_nope").status_code == 404

    chunk = client.get(f"/api/documents/{doc_id}/text").json()["chunks"][0]
    loc = client.post(f"/api/documents/{doc_id}/locate", json={"chunk_id": chunk["chunk_id"], "claim": "Wind turbines: 3,800,000"}).json()
    assert loc["method"] == "text" and loc["chunk_id"] == chunk["chunk_id"]
    client.delete(f"/api/documents/{doc_id}")


@pytest.mark.skipif(not ocr.tesseract_available(), reason="Tesseract is not installed")
def test_scanned_image_is_read_with_ocr_and_highlighted():
    import io
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 420), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    for i, line in enumerate(["Invoice No: NW-2026-0419", "Total Due: INR 991,200"]):
        draw.text((60, 80 + i * 140), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = _upload("invoice.png", buf.getvalue(), "image/png")
    assert doc["ocr_pages"] == 1 and doc["chunk_count"] >= 1
    doc_id = doc["doc_id"]
    loc = client.post(f"/api/documents/{doc_id}/locate", json={
        "page": 1, "claim": "Total Due: INR 991,200", "exact": True, "passage": "Total Due: INR 991,200"}).json()
    assert loc["method"] == "sentence" and len(loc["rects"]) == 1
    x0, y0, x1, y1 = loc["rects"][0]
    assert y0 > 0.4  # the second line, not the first
    assert client.get(f"/api/documents/{doc_id}/pages/1").status_code == 200
    client.delete(f"/api/documents/{doc_id}")


def test_upload_accepts_new_types_and_rejects_others():
    assert client.post("/api/documents/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.get("/api/documents/doc_missing/info").status_code == 404
    assert client.get("/api/documents/bad id!/info").status_code in (400, 404)


def test_extraction_presets_and_request_validation():
    presets = client.get("/api/extract/presets").json()
    assert {p["key"] for p in presets["presets"]} == {"invoice", "receipt", "purchase_order", "contract", "resume",
                                                       "paper", "report", "bank_statement"}
    assert "date" in presets["types"]
    assert client.post("/api/extract/stream", json={"document_ids": ["doc_missing"], "fields": []}).status_code == 400
    assert client.post("/api/extract/stream", json={"document_ids": ["doc_missing"], "preset": "invoice"}).status_code == 404
