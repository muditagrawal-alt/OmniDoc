import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pytest
except ImportError:
    pytest = None
from export.report_compiler import ReportCompiler


def test_report_compiler_pdf():
    compiler = ReportCompiler()
    messages = [
        {
            "role": "user",
            "content": "Can you compute the net enterprise value growth between 2023 and 2024?",
        },
        {
            "role": "assistant",
            "content": "Based on the 10-K filing excerpts, enterprise value increased from $100M to $125M.",
            "math_result": {
                "expression": "(125 - 100) / 100 * 100",
                "result": 25.0,
                "unit": "%",
                "verified": True
            },
            "sources": [
                {
                    "title": "Form 10-K Section 7",
                    "doc_id": "doc_10k_2024",
                    "chunk_id": "c_99",
                    "snippet": "Total enterprise valuation recorded at $125M as of December 31, 2024."
                }
            ],
            "graph_entities": [
                {"name": "Enterprise Value", "type": "Metric", "description": "Valuation metric"},
                {"name": "FY2024", "type": "TimePeriod", "description": "Fiscal year"}
            ]
        }
    ]

    metadata = {
        "model_name": "OmniDoc Qwen 2.5 7B",
        "groundedness_score": 0.985,
        "doc_count": 2
    }

    pdf_bytes = compiler.compile_pdf(
        title="Enterprise Valuation Growth Analysis",
        messages=messages,
        metadata=metadata
    )

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 5000
    assert pdf_bytes.startswith(b"%PDF")


def test_report_compiler_docx():
    compiler = ReportCompiler()
    messages = [
        {
            "role": "user",
            "content": "Can you compute the net enterprise value growth between 2023 and 2024?",
        },
        {
            "role": "assistant",
            "content": "Based on the 10-K filing excerpts, enterprise value increased from $100M to $125M.",
            "math_result": {
                "expression": "(125 - 100) / 100 * 100",
                "result": 25.0,
                "unit": "%",
                "verified": True
            },
            "sources": [
                {
                    "title": "Form 10-K Section 7",
                    "doc_id": "doc_10k_2024",
                    "chunk_id": "c_99",
                    "snippet": "Total enterprise valuation recorded at $125M as of December 31, 2024."
                }
            ],
            "graph_entities": [
                {"name": "Enterprise Value", "type": "Metric", "description": "Valuation metric"}
            ]
        }
    ]

    docx_bytes = compiler.compile_docx(
        title="Enterprise Valuation Growth Analysis",
        messages=messages,
        metadata={"model_name": "OmniDoc Qwen 2.5 7B", "groundedness_score": 0.985}
    )

    assert isinstance(docx_bytes, bytes)
    assert len(docx_bytes) > 5000
    # DOCX is a zip archive starting with PK\x03\x04
    assert docx_bytes.startswith(b"PK")


if __name__ == "__main__":
    print("Testing ReportCompiler PDF (WeasyPrint)...")
    test_report_compiler_pdf()
    print("✓ PDF compiled successfully!")
    print("Testing ReportCompiler DOCX (python-docx)...")
    test_report_compiler_docx()
    print("✓ DOCX compiled successfully!")
    print("All ReportCompiler tests passed! 🚀")
