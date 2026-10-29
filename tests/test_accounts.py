"""
Accounts on a hosted OmniDoc (OMNIDOC_ACCOUNTS=1): sign-in with e-mailed codes, Google or GitHub,
private libraries, limits and account deletion; and the rolling memory of long conversations.

Runs against a throwaway data folder; no e-mail is sent and no provider is called.
"""
import os
import sys
import tempfile

_TMP_DATA = tempfile.mkdtemp(prefix="omnidoc-accounts-test-")
os.environ.setdefault("OMNIDOC_DATA_DIR", _TMP_DATA)
os.environ.setdefault("OMNIDOC_WARMUP", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from core import accounts, chat_memory  # noqa: E402

client = TestClient(server.app)


@pytest.fixture
def hosted(monkeypatch):
    """Accounts on, e-mail codes captured instead of sent."""
    sent = {}
    monkeypatch.setenv("OMNIDOC_ACCOUNTS", "1")
    monkeypatch.setenv("OMNIDOC_OTP_LOG", "1")
    monkeypatch.setattr(accounts, "send_code_email", lambda to, code: sent.__setitem__(to, code))
    return sent


def _sign_in(sent, email):
    assert client.post("/api/auth/code/request", json={"email": email}).status_code == 200
    resp = client.post("/api/auth/code/verify", json={"email": email, "code": sent[email]})
    assert resp.status_code == 200, resp.text
    return {"X-OmniDoc-Token": resp.json()["token"]}, resp.json()["user"]


def test_a_local_install_needs_no_sign_in(monkeypatch):
    monkeypatch.delenv("OMNIDOC_ACCOUNTS", raising=False)
    assert client.get("/api/auth/methods").json()["accounts"] is False
    assert client.get("/api/chats").status_code == 200


def test_every_api_call_needs_a_session_with_accounts(hosted):
    assert client.get("/api/chats").status_code == 401
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/health").status_code == 200
    methods = client.get("/api/auth/methods").json()
    assert methods["accounts"] and methods["email"] and not methods["github"]
    # The e-mail-only local profile cannot be used to sign in to a hosted server.
    assert client.post("/api/auth/login", json={"email": "a@example.com"}).status_code in (401, 404)


def test_signing_in_with_an_emailed_code(hosted):
    email = "priya@example.com"
    assert client.post("/api/auth/code/request", json={"email": "not-an-address"}).status_code == 422
    assert client.post("/api/auth/code/request", json={"email": email}).status_code == 200
    code = hosted[email]
    assert len(code) == 6 and code.isdigit()
    wrong = "000000" if code != "000000" else "111111"
    bad = client.post("/api/auth/code/verify", json={"email": email, "code": wrong})
    assert bad.status_code == 400 and "4 tries left" in bad.json()["detail"]
    ok = client.post("/api/auth/code/verify", json={"email": email, "code": code})
    assert ok.status_code == 200
    headers = {"X-OmniDoc-Token": ok.json()["token"]}
    assert client.get("/api/auth/me", headers=headers).json()["user"]["email"] == email
    assert client.get("/api/chats", headers=headers).status_code == 200
    # A code works once, and a new one cannot be requested within a minute.
    assert client.post("/api/auth/code/verify", json={"email": email, "code": code}).status_code == 400
    assert client.post("/api/auth/code/request", json={"email": email}).status_code == 429
    # Only a hash of the session token is stored.
    assert not server.db.conn.execute("SELECT 1 FROM sessions WHERE token = ?", (headers["X-OmniDoc-Token"],)).fetchone()


def test_five_wrong_codes_spend_the_code(hosted):
    email = "five@example.com"
    client.post("/api/auth/code/request", json={"email": email})
    code = hosted[email]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        client.post("/api/auth/code/verify", json={"email": email, "code": wrong})
    resp = client.post("/api/auth/code/verify", json={"email": email, "code": code})
    assert resp.status_code == 429 and "Too many" in resp.json()["detail"]


def test_an_allow_list_limits_who_may_sign_in(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_ALLOWED_EMAILS", "@kestrel.example,boss@other.example")
    assert client.post("/api/auth/code/request", json={"email": "someone@gmail.com"}).status_code == 403
    assert client.post("/api/auth/code/request", json={"email": "meera@kestrel.example"}).status_code == 200
    assert client.post("/api/auth/code/request", json={"email": "boss@other.example"}).status_code == 200


def test_each_account_sees_only_its_own_documents(hosted):
    a, user_a = _sign_in(hosted, "ana@example.com")
    b, user_b = _sign_in(hosted, "ben@example.com")
    server.db.add_document("doc_ana1", "ana.pdf", "hash-shared", 1000, "pdf", owner_id=user_a["id"])
    server.db.add_document("doc_ben1", "ben.pdf", "hash-shared", 1000, "pdf", owner_id=user_b["id"])  # the same file, twice
    listed = [d["id"] for d in client.get("/api/documents", headers=a).json()["documents"]]
    assert listed == ["doc_ana1"]
    assert client.get("/api/documents/doc_ben1/info", headers=a).status_code == 404
    assert client.delete("/api/documents/doc_ben1", headers=a).status_code == 404
    # A question may read only the asker's documents, whatever it names.
    assert server.scoped_ids(["doc_ben1"], user_a["id"]) == ["doc_ana1"]
    assert server.scoped_ids([], user_b["id"]) == ["doc_ben1"]
    _, user_c = _sign_in(hosted, "cara@example.com")
    assert server.scoped_ids([], user_c["id"]) == [server.NO_DOCUMENTS]


def test_daily_limits_and_the_storage_cap(hosted, monkeypatch):
    headers, user = _sign_in(hosted, "limits@example.com")
    monkeypatch.setenv("OMNIDOC_DAILY_QUESTIONS", "1")
    server.check_quota(user["id"], "questions")
    server.db.count_usage(user["id"], "questions")
    with pytest.raises(server.HTTPException) as exc:
        server.check_quota(user["id"], "questions")
    assert exc.value.status_code == 429
    monkeypatch.setenv("OMNIDOC_STORAGE_MB", "0")
    resp = client.post("/api/documents/upload", headers=headers, files={"file": ("note.txt", b"quarterly figures", "text/plain")})
    assert resp.status_code == 413 and "library is full" in resp.json()["detail"]
    usage = client.get("/api/account", headers=headers).json()
    assert usage["usage"]["questions"] == 1 and usage["limits"]["questions_per_day"] == 1
    # Administrators have no limits.
    monkeypatch.setenv("OMNIDOC_ADMIN_EMAILS", "limits@example.com")
    server.check_quota(user["id"], "questions")
    assert client.get("/api/account", headers=headers).json()["limits"] is None


def test_signing_in_with_github(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("OMNIDOC_GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("OMNIDOC_PUBLIC_URL", "https://omnidoc.example")
    start = client.get("/api/auth/oauth/github/start", follow_redirects=False)
    assert start.status_code == 302 and start.headers["location"].startswith("https://github.com/login/oauth/authorize?")
    state = dict(p.split("=", 1) for p in start.headers["location"].split("?", 1)[1].split("&"))["state"]

    class Reply:
        def __init__(self, data, status=200):
            self.data, self.status_code = data, status

        def json(self):
            return self.data
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **k: Reply({"access_token": "gh-token"}))
    monkeypatch.setattr(httpx, "get", lambda url, **k: Reply(
        [{"email": "dev@users.example", "verified": True, "primary": True}] if url.endswith("/emails")
        else {"login": "devname", "name": "Dev Name", "avatar_url": "https://avatars.example/1"}))
    done = client.get(f"/api/auth/oauth/github/callback?code=abc&state={state}", follow_redirects=False)
    assert done.status_code == 302 and done.headers["location"].startswith("https://omnidoc.example/#auth=")
    token = done.headers["location"].split("#auth=", 1)[1]
    me = client.get("/api/auth/me", headers={"X-OmniDoc-Token": token}).json()["user"]
    assert me["email"] == "dev@users.example" and me["provider"] == "github"
    # A state works once.
    again = client.get(f"/api/auth/oauth/github/callback?code=abc&state={state}", follow_redirects=False)
    assert "#auth_error=" in again.headers["location"]


def test_deleting_an_account_removes_its_data(hosted, monkeypatch):
    headers, user = _sign_in(hosted, "leaving@example.com")
    server.db.add_document("doc_leaving", "x.pdf", "hash-leaving", 10, "pdf", owner_id=user["id"])
    chat = client.post("/api/chats", json={"title": "Q4"}, headers=headers).json()["chat"]
    removed = []
    monkeypatch.setattr(server, "_remove_document", lambda doc_id: (removed.append(doc_id), server.db.delete_document(doc_id)))
    monkeypatch.setattr(server, "get_pipeline", lambda: type("P", (), {"refresh_records": lambda self: None})())
    assert client.delete("/api/account", headers=headers).status_code == 200
    assert removed == ["doc_leaving"]
    assert server.db.get_user(user["id"]) is None and server.db.get_chat(chat["id"]) is None
    assert client.get("/api/chats", headers=headers).status_code == 401


def test_long_conversations_keep_a_rolling_summary():
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(10)]
    history = chat_memory.history_for(messages, "Asked about Ulta's Q4 net sales ($3.2 billion).", 4)
    assert history[0] == {"role": "summary", "content": "Asked about Ulta's Q4 net sales ($3.2 billion)."}
    assert [t["content"] for t in history[1:]] == [f"turn {i}" for i in range(4, 10)]
    # Turns that left the window before the summary caught up keep their questions.
    behind = chat_memory.history_for(messages, "", 0)
    assert behind[0]["content"].startswith("Earlier questions: turn 0 | turn 2")

    saved = {}
    chat = {"id": "c1", "memory": "", "memory_upto": 0}
    changed = chat_memory.update("c1", lambda cid: messages, lambda cid: chat,
                                 lambda cid, text, upto: saved.update(text=text, upto=upto),
                                 lambda prompt: "The user asked about turns 0 to 3.")
    assert changed and saved == {"text": "The user asked about turns 0 to 3.", "upto": 4}
    from agents.understanding_agent import QueryUnderstandingAgent
    text = QueryUnderstandingAgent._history_text(history)
    assert text.startswith("Earlier in this conversation (summary): Asked about Ulta") and "User: turn 4" in text


def test_long_answers_are_stored_compressed():
    from db_store import OmniDocDB
    db = OmniDocDB(os.path.join(tempfile.mkdtemp(), "c.db"))
    db.create_chat("c1")
    metadata = {"sources": [{"snippet": f"Net sales were $3,226.8 million in passage {i}."} for i in range(80)]}
    db.add_message("c1", "assistant", "answer", metadata=metadata)
    raw = db.conn.execute("SELECT metadata FROM messages").fetchone()[0]
    assert raw.startswith("z1:") and len(raw) < len(str(metadata)) / 3
    assert db.get_messages("c1")[0]["metadata"] == metadata


def test_library_records_are_kept_per_account():
    from retrieval.table_store import TableStore, library_id
    from retrieval.records import LibraryRecords
    from agents.structured_data_agent import StructuredDataAgent
    folder = tempfile.mkdtemp()
    store = TableStore(os.path.join(folder, "tables.db"))
    records = LibraryRecords(store, os.path.join(folder, "records"))
    records.save("doc_a", {"doc_type": "invoice", "fields": [{"label": "Total due", "value": 362968, "status": "found"}]})
    records.save("doc_b", {"doc_type": "invoice", "fields": [{"label": "Total due", "value": 999, "status": "found"}]})
    records.refresh([{"id": "doc_a", "title": "a.png", "owner_id": "usr_ana"},
                     {"id": "doc_b", "title": "b.png", "owner_id": "usr_ben"}])
    agent = StructuredDataAgent(type("T", (), {"table_store": store})())
    ana = agent._library_tables("total due across all invoices in my library", {"library": True}, "usr_ana")
    assert ana and all(t["doc_id"] == library_id("usr_ana") for t in ana)
    rows = store.run_select(f'SELECT * FROM "{[t for t in ana if "records" in t["table"]][0]["table"]}"',
                            [t["table"] for t in ana])["rows"]
    assert rows == [["a.png", 362968, None]]
    # An account with no documents left loses its tables.
    records.refresh([{"id": "doc_a", "title": "a.png", "owner_id": "usr_ana"}])
    assert library_id("usr_ben") not in store.library_ids()
