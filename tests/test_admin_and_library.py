"""
The administrator role and its overview, personal API tokens, each user's own answer model, and
the library-wide views (tables, records, timeline) on a hosted OmniDoc.
"""
import contextvars
import json
from types import SimpleNamespace

import pytest

import server
from agents import llm_providers
from test_account_security import client, hosted, signup  # noqa: F401  (hosted is a fixture)


def _me(headers):
    return client.get("/api/auth/me", headers=headers).json()["user"]


def test_the_setup_code_makes_an_account_the_administrator(hosted):
    _, owner, _ = signup("Mudit")
    _, member, _ = signup("Kavya")
    assert _me(owner)["admin"] is False
    assert client.get("/api/admin/overview", headers=owner).status_code == 403

    wrong = client.post("/api/admin/claim", headers=owner, json={"code": "not-the-code"})
    assert wrong.status_code == 403 and "log" in wrong.json()["detail"]
    assert client.post("/api/admin/claim", headers=owner, json={"code": server.admin_setup_code()}).status_code == 200
    assert _me(owner)["admin"] is True and _me(member)["admin"] is False

    overview = client.get("/api/admin/overview", headers=owner).json()
    assert overview["health"]["stores"]["sqlite"] == "ok"
    assert overview["stats"]["accounts"] >= 2
    assert any(a["name"] == "Mudit" for a in overview["admins"])
    assert client.get("/api/admin/overview", headers=member).status_code == 403

    sent = client.post("/api/admin/announce", headers=owner, json={"title": "Tables tab", "body": "Every table in one place."})
    assert sent.status_code == 200
    assert client.post("/api/admin/announce", headers=member, json={"title": "No"}).status_code == 403
    notices = client.get("/api/notices", headers=member).json()["notices"]
    assert any(n["title"] == "Tables tab" and n["kind"] == "announcement" for n in notices)


def test_api_tokens_sign_in_until_revoked(hosted):
    _, headers, _ = signup("Asha")
    made = client.post("/api/account/tokens", headers=headers, json={"name": "Claude Code"})
    assert made.status_code == 200
    token = {"X-OmniDoc-Token": made.json()["token"]}
    assert client.get("/api/documents", headers=token).status_code == 200
    sessions = client.get("/api/account/sessions", headers=headers).json()["sessions"]
    entry = next(s for s in sessions if s["device"] == "API token: Claude Code")
    assert client.delete(f"/api/account/sessions/{entry['id']}", headers=headers).status_code == 200
    assert client.get("/api/documents", headers=token).status_code == 401


def test_each_user_chooses_their_own_answer_model(hosted, monkeypatch):
    current = server.current_model()
    monkeypatch.setattr(server, "available_models", lambda: [{"name": current}, {"name": "groq:gpt-oss-120b"}])
    assert server.chosen_model(server.QueryRequest(query="q")) is None
    assert server.chosen_model(server.QueryRequest(query="q", model=current)) is None
    assert server.chosen_model(server.QueryRequest(query="q", model="groq:gpt-oss-120b")) == "groq:gpt-oss-120b"
    with pytest.raises(server.HTTPException) as exc:
        server.chosen_model(server.QueryRequest(query="q", model="someone:else"))
    assert exc.value.status_code == 400

    _, headers, _ = signup("Imran")
    listed = client.get("/api/models", headers=headers).json()
    assert listed["can_set_default"] is False  # anyone picks for themselves; only an administrator sets the default

    def inside_one_question():
        llm_providers.prefer_answer_model("nvidia:default-model", "groq:gpt-oss-120b")
        return (llm_providers._answer_spec("nvidia:default-model"),
                llm_providers._answer_spec("gemini:gemini-3.5-flash-lite"))

    swapped, untouched = contextvars.copy_context().run(inside_one_question)
    assert swapped == "groq:gpt-oss-120b" and untouched == "gemini:gemini-3.5-flash-lite"
    assert llm_providers._answer_spec("nvidia:default-model") == "nvidia:default-model"  # other questions keep the default


def test_library_views_show_only_the_users_own_documents(hosted, monkeypatch):
    _, headers, body = signup("Lena")
    user_id = body["user"]["id"]
    server.db.add_document("doc_lena1", "contract.pdf", "hash-lena-1", 900, "pdf", owner_id=user_id)
    server.db.add_document("doc_other1", "secret.pdf", "hash-other-1", 900, "pdf", owner_id="usr_someone_else")
    records = server.DATA_DIR / "records"
    records.mkdir(parents=True, exist_ok=True)
    (records / "doc_lena1.json").write_text(json.dumps({
        "fields": [{"name": "effective_date", "label": "Effective date", "value": "14 January 2025", "status": "found", "page": 1}],
        "validation": [{"name": "dates", "status": "pass"}],
    }))

    chunks = {
        "doc_lena1": [SimpleNamespace(chunk_id="doc_lena1_p1_c0", doc_id="doc_lena1", page_number=1,
                                      text="Payment is due on 11 September 2026. The agreement starts on 1 February 2025. "
                                           "Balance sheet INR crore 31 Mar 2024 31 Mar 2023 412 356.")],
        "doc_other1": [SimpleNamespace(chunk_id="doc_other1_p1_c0", doc_id="doc_other1", page_number=1,
                                       text="The other library's merger closed on 3 March 2024.")],
    }
    tables = [
        {"doc_id": "doc_lena1", "table": "t_fees", "table_id": "p1_t1", "title": "Fees", "page": 1, "n_rows": 4,
         "columns": [{"name": "Item"}, {"name": "Amount"}]},
        {"doc_id": "doc_other1", "table": "t_secret", "table_id": "p1_t1", "title": "Secret", "page": 1, "n_rows": 2, "columns": []},
    ]
    fake = SimpleNamespace(
        lance_store=SimpleNamespace(get_document_chunks=lambda doc_id: chunks.get(doc_id, [])),
        table_store=SimpleNamespace(tables_for=lambda ids: [t for t in tables if t["doc_id"] in ids]),
    )
    monkeypatch.setattr(server, "get_pipeline", lambda: fake)

    listed = client.get("/api/tables", headers=headers).json()["tables"]
    assert [t["table"] for t in listed] == ["t_fees"] and listed[0]["columns"] == ["Item", "Amount"]

    recs = client.get("/api/records", headers=headers).json()["records"]
    assert [r["doc_id"] for r in recs] == ["doc_lena1"]
    assert recs[0]["fields"][0]["value"] == "14 January 2025" and recs[0]["checks"][0]["status"] == "pass"

    events = client.get("/api/timeline", headers=headers).json()["events"]
    assert [e["date"][:10] for e in events] == ["2025-02-01", "2026-09-11"]
    assert all(e["document"] == "contract.pdf" for e in events)


def test_page_images_load_with_the_media_cookie_and_nothing_else_does(hosted):
    _, headers, _ = signup("Ravi")
    client.cookies.clear()
    assert client.get("/api/documents/doc_missing01/pages/1").status_code == 401

    set_cookie = client.post("/api/auth/media", headers=headers)
    assert set_cookie.status_code == 200
    cookie = set_cookie.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/documents" in cookie

    # The cookie signs in an image or file request (the document does not exist: 404, not 401) ...
    assert client.get("/api/documents/doc_missing01/pages/1").status_code == 404
    assert client.get("/api/documents/doc_missing01/file").status_code == 404
    # ... and nothing else: not the document list, not a write.
    assert client.get("/api/documents").status_code == 401
    assert client.delete("/api/documents/doc_missing01").status_code == 401

    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/media").status_code == 401


def test_guests_get_the_media_cookie_for_the_demo_library(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_DEMO", "1")
    from test_account_security import proof
    guest = client.post("/api/auth/guest", json={"pow": proof()})
    assert guest.status_code == 200
    client.cookies.clear()
    assert client.post("/api/auth/media", headers={"X-OmniDoc-Token": guest.json()["token"]}).status_code == 200
    assert client.get("/api/documents/doc_missing02/pages/1").status_code == 404  # signed in by the cookie
    client.cookies.clear()
