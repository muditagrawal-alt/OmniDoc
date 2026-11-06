"""
Tables in PDFs are read cell by cell from the page's words, so decimals, thousands separators and
spaces survive whichever PyMuPDF is installed (2.x's own cell text turned "16.5%" into "165%\\n.").
"""
import importlib.util
from pathlib import Path

import fitz

from parsing.docling_parser import DoclingParser

ROOT = Path(__file__).resolve().parent.parent


def _samples():
    spec = importlib.util.spec_from_file_location("make_samples", ROOT / "deploy" / "demo" / "make_samples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_demo_annual_report_table_keeps_its_figures(tmp_path):
    samples = _samples()
    path = tmp_path / "report.pdf"
    samples.annual_report(2025, samples.FY2025).save(str(path))
    doc = fitz.open(str(path))
    tables = [norm for page in doc for _, norm in DoclingParser._page_tables(page)]
    assert tables, "the financial highlights table was not found"
    text = repr(tables[0])
    for expected in ("16.5", "1284", "Subscription revenue", "20.1"):
        assert expected in text.replace(",", ""), (expected, text[:400])
    assert "165" not in text.replace("16.5", "").replace("1650", ""), text[:400]
