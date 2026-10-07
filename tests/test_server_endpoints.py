"""
Integration tests for the OmniDoc FastAPI server.

Runs against a throwaway data directory so the real .data/ database is never touched.
"""
import os
import sys
import tempfile

_TMP_DATA = tempfile.mkdtemp(prefix="omnidoc-test-")
os.environ["OMNIDOC_DATA_DIR"] = _TMP_DATA

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from server import app  # noqa: E402

client = TestClient(app)


def _login(email: str, name: str = "") -> dict:
    resp = client.post("/api/auth/login", json={"provider": "local", "email": email, "name": name})
    assert resp.status_code == 200
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "OmniDoc"
    assert data["stores"]["sqlite"] == "ok"


def test_auth_and_chat_flow():
    login = _login("analyst@example.com", "Research Analyst")
    token = login["token"]
    # The token is an opaque session secret, never the user id.
    assert token != login["user"]["id"]
    assert not token.startswith("usr_")
    assert login["user"]["name"] == "Research Analyst"

    me = client.get("/api/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "analyst@example.com"

    chat = client.post("/api/chats", json={"title": "Q3 review"}, headers=_auth(token))
    assert chat.status_code == 200
    chat_id = chat.json()["chat"]["id"]

    listed = client.get("/api/chats", headers=_auth(token)).json()["chats"]
    assert chat_id in [c["id"] for c in listed]

    assert client.patch(f"/api/chats/{chat_id}", json={"title": "Q3 valuation"}, headers=_auth(token)).status_code == 200
    assert client.get(f"/api/chats/{chat_id}", headers=_auth(token)).json()["chat"]["title"] == "Q3 valuation"
    assert client.delete(f"/api/chats/{chat_id}", headers=_auth(token)).status_code == 200
    assert client.get(f"/api/chats/{chat_id}", headers=_auth(token)).status_code == 404

    client.post("/api/auth/logout", headers=_auth(token))
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401


def test_chats_are_private_to_their_owner():
    owner = _login("owner@example.com")["token"]
    other = _login("other@example.com")["token"]
    chat_id = client.post("/api/chats", json={"title": "Private"}, headers=_auth(owner)).json()["chat"]["id"]

    assert client.get(f"/api/chats/{chat_id}", headers=_auth(other)).status_code == 404
    assert client.patch(f"/api/chats/{chat_id}", json={"title": "x"}, headers=_auth(other)).status_code == 404
    assert client.delete(f"/api/chats/{chat_id}", headers=_auth(other)).status_code == 404
    # Requests without a token act as the local user, who does not own it either.
    assert client.get(f"/api/chats/{chat_id}").status_code == 404
    assert chat_id not in [c["id"] for c in client.get("/api/chats", headers=_auth(other)).json()["chats"]]
    assert client.get(f"/api/chats/{chat_id}", headers=_auth(owner)).status_code == 200


def test_forged_or_expired_tokens_are_rejected():
    user_id = _login("victim@example.com")["user"]["id"]
    # Presenting someone's user id as a token must not authenticate as them.
    assert client.get("/api/auth/me", headers=_auth(user_id)).status_code == 401
    assert client.get("/api/chats", headers=_auth("sess_not_a_real_token")).status_code == 401


def test_cors_allows_only_local_frontend():
    evil = client.options("/api/chats", headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "GET",
    })
    assert "access-control-allow-origin" not in evil.headers

    local = client.options("/api/chats", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    })
    assert local.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_upload_validation():
    bad_type = client.post("/api/documents/upload", files={"file": ("../../payload.exe", b"MZ", "application/octet-stream")})
    assert bad_type.status_code == 415
    empty = client.post("/api/documents/upload", files={"file": ("notes.txt", b"", "text/plain")})
    assert empty.status_code == 400
    assert client.delete("/api/documents/bad id!").status_code == 400


MATH_RESULT = {
    "task": "Multiple expansion",
    "formula": r"\frac{125}{80}",
    "exact_result": 1.5625,
    "units": "x",
    "inputs": {"ev_2024": 125.0, "ev_2022": 80.0},
    "assumptions": ["Values in USD millions"],
    "code_executed": "125/80",
}


def _sample_messages(snippet: str = "Revenue reported at $125M.") -> list:
    return [
        {"role": "user", "content": "How much did the valuation multiple expand?"},
        {
            "role": "assistant",
            "content": "The multiple expanded to **1.56x** [1].\n\n| Year | EV |\n|---|---|\n| 2022 | 80 |\n| 2024 | 125 |",
            "math_result": MATH_RESULT,
            "math_results": [MATH_RESULT],
            "sources": [{"n": 1, "kind": "chunk", "title": "Annual report", "doc_id": "doc_fin", "snippet": snippet}],
        },
    ]


def test_export_pdf_and_docx_endpoints():
    meta = {"model_name": "qwen2.5:7b-instruct", "groundedness_score": 0.9}
    pdf = client.post("/api/export/pdf", json={"title": "Valuation review", "messages": _sample_messages(), "metadata": meta})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    docx = client.post("/api/export/docx", json={"title": "Valuation review", "messages": _sample_messages(), "metadata": meta})
    assert docx.status_code == 200
    assert "wordprocessingml" in docx.headers["content-type"]
    assert docx.content.startswith(b"PK")


def test_export_handles_non_latin_titles_and_control_characters():
    title = "राजस्व विश्लेषण"
    messages = _sample_messages(snippet="Extracted text with a control char \x03 from a PDF.")
    for fmt in ("pdf", "docx"):
        resp = client.post(f"/api/export/{fmt}", json={"title": title, "messages": messages, "metadata": {}})
        assert resp.status_code == 200, resp.text
        disposition = resp.headers["content-disposition"]
        assert "filename*=UTF-8''" in disposition
        disposition.encode("latin-1")  # must be a valid header value


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
