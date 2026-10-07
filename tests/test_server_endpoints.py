"""
Integration tests for OmniDoc FastAPI server endpoints.
"""
import sys
import os
import io

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "OmniDoc Multi-Agent Graph RAG"


def test_auth_and_chat_flow():
    # 1. Login with Google
    login_resp = client.post("/api/auth/login", json={
        "provider": "google",
        "email": "test_scientist@zenith.ai",
        "name": "Dr. Zenith AI",
        "avatar_url": "https://api.dicebear.com/7.x/identicon/svg?seed=zenith"
    })
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    token = login_data["token"]
    assert token.startswith("usr_")
    assert login_data["user"]["name"] == "Dr. Zenith AI"

    # 2. Check /api/auth/me with Bearer token
    me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["email"] == "test_scientist@zenith.ai"

    # 3. Create a chat session
    chat_resp = client.post("/api/chats", json={"title": "Q3 Financial Graph Audit"}, headers={"Authorization": f"Bearer {token}"})
    assert chat_resp.status_code == 200
    chat_id = chat_resp.json()["chat"]["id"]

    # 4. List chats
    list_resp = client.get("/api/chats", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200
    chat_ids = [c["id"] for c in list_resp.json()["chats"]]
    assert chat_id in chat_ids

    # 5. Rename chat
    rename_resp = client.patch(f"/api/chats/{chat_id}", json={"title": "Q3 Financial Analysis & Valuation"})
    assert rename_resp.status_code == 200

    # 6. Delete chat
    del_resp = client.delete(f"/api/chats/{chat_id}")
    assert del_resp.status_code == 200


def test_export_pdf_and_docx_endpoints():
    sample_messages = [
        {
            "role": "user",
            "content": "Analyze the revenue multiple expansion from 2022 to 2024."
        },
        {
            "role": "assistant",
            "content": "Enterprise valuation expanded significantly over the two-year horizon.",
            "math_result": {
                "expression": "125.0 / 80.0",
                "result": 1.5625,
                "unit": "x",
                "verified": True
            },
            "sources": [
                {
                    "title": "Securities Filing",
                    "doc_id": "doc_fin_10k",
                    "snippet": "Gross revenue reported at $125M with enterprise valuation expansion."
                }
            ]
        }
    ]

    # Test PDF Export
    pdf_resp = client.post("/api/export/pdf", json={
        "title": "Valuation Multiple Audit Report",
        "messages": sample_messages,
        "metadata": {"model_name": "OmniDoc Qwen 2.5 7B", "groundedness_score": 0.985}
    })
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert len(pdf_resp.content) > 5000
    assert pdf_resp.content.startswith(b"%PDF")

    # Test DOCX Export
    docx_resp = client.post("/api/export/docx", json={
        "title": "Valuation Multiple Audit Report",
        "messages": sample_messages,
        "metadata": {"model_name": "OmniDoc Qwen 2.5 7B", "groundedness_score": 0.985}
    })
    assert docx_resp.status_code == 200
    assert "wordprocessingml" in docx_resp.headers["content-type"]
    assert len(docx_resp.content) > 5000
    assert docx_resp.content.startswith(b"PK")


if __name__ == "__main__":
    print("Running Server Endpoint Verification Tests...")
    test_health_check()
    print("✓ test_health_check passed!")
    test_auth_and_chat_flow()
    print("✓ test_auth_and_chat_flow passed!")
    test_export_pdf_and_docx_endpoints()
    print("✓ test_export_pdf_and_docx_endpoints passed!")
    print("All Server Tests Passed! 🚀")
