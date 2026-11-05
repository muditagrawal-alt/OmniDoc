"""
The free trial and bring-your-own-key on a hosted OmniDoc: three answers on the server's keys,
then the user's own key, kept in the browser (sent per request) or, if they choose, encrypted on
the server. A user's keys must reach every thread an answer uses, never mix with the server's keys,
and never outlive the request.
"""
import base64
import contextvars
import json
import os
import sys
import tempfile
import threading

_TMP_DATA = tempfile.mkdtemp(prefix="omnidoc-keys-test-")
os.environ.setdefault("OMNIDOC_DATA_DIR", _TMP_DATA)
os.environ.setdefault("OMNIDOC_WARMUP", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from agents import llm_providers  # noqa: E402
from core import abuse, accounts  # noqa: E402

client = TestClient(server.app)
GROQ_KEY = "gsk_" + "u" * 40


def keys_header(keys):
    return base64.urlsafe_b64encode(json.dumps(keys).encode()).decode().rstrip("=")


@pytest.fixture
def hosted(monkeypatch):
    sent = {}
    monkeypatch.setenv("OMNIDOC_ACCOUNTS", "1")
    monkeypatch.setenv("OMNIDOC_OTP_LOG", "1")
    monkeypatch.setattr(accounts, "send_code_email", lambda to, code: sent.__setitem__(to, code))
    abuse.limiter.reset()
    return sent


def sign_in(sent, email):
    server.db.conn.execute("UPDATE otp_codes SET last_sent = 0, sends = 0 WHERE email = ?", (email,))
    server.db.conn.commit()
    client.post("/api/auth/code/request", json={"email": email})
    body = client.post("/api/auth/code/verify", json={"email": email, "code": sent[email]},
                       headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/141.0 Safari/537.36"}).json()
    return {"X-OmniDoc-Token": body["token"]}, body["user"]


class FakeRequest:
    def __init__(self, ip="203.0.113.5"):
        self.client = type("C", (), {"host": ip})()
        self.headers = {}
        self.state = type("S", (), {})()


def test_three_free_answers_then_the_users_own_key(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_TRIAL_ANSWERS", "3")
    _, user = sign_in(hosted, "trial@example.com")
    for _ in range(3):
        server._answer_gate(user["id"], FakeRequest())
        server._charge(user["id"])
    with pytest.raises(server.HTTPException) as exc:
        server._answer_gate(user["id"], FakeRequest())
    assert exc.value.status_code == 402 and exc.value.headers["X-OmniDoc-Need"] == "api-key"
    assert "3 free answers" in exc.value.detail

    def with_own_key():
        llm_providers.use_keys({"groq": GROQ_KEY})
        server._answer_gate(user["id"], FakeRequest())  # no longer blocked
        server._charge(user["id"])
    contextvars.copy_context().run(with_own_key)
    assert server.db.trial_used(user["id"]) == 3  # answers with the user's key do not use the trial
    account = client.get("/api/account", headers=sign_in(hosted, "trial@example.com")[0]).json()
    assert account["trial"] == {"limit": 3, "used": 3}


def test_one_network_cannot_farm_free_answers_with_many_accounts(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_TRIAL_PER_IP", "2")
    users = [sign_in(hosted, f"farm{i}@example.com")[1] for i in range(3)]
    server._answer_gate(users[0]["id"], FakeRequest("198.51.100.9"))
    server._answer_gate(users[1]["id"], FakeRequest("198.51.100.9"))
    with pytest.raises(server.HTTPException) as exc:
        server._answer_gate(users[2]["id"], FakeRequest("198.51.100.9"))
    assert exc.value.status_code == 402 and "network" in exc.value.detail


def test_the_browsers_keys_apply_to_that_request_only(hosted):
    headers, _ = sign_in(hosted, "device@example.com")
    with_key = client.get("/api/account", headers={**headers, "X-OmniDoc-Keys": keys_header({"groq": GROQ_KEY, "evil": "x" * 20})}).json()
    assert with_key["own_keys"] == {"server": [], "in_use": ["groq"]}  # unknown providers are dropped
    assert client.get("/api/account", headers=headers).json()["own_keys"]["in_use"] == []  # nothing carried over
    garbled = client.get("/api/account", headers={**headers, "X-OmniDoc-Keys": "not base64 json"})
    assert garbled.status_code == 200 and garbled.json()["own_keys"]["in_use"] == []


def test_a_key_can_be_kept_encrypted_on_the_server(hosted, monkeypatch):
    headers, user = sign_in(hosted, "server-key@example.com")
    monkeypatch.setattr(llm_providers, "check_key", lambda provider, key: (key == GROQ_KEY, "Groq did not accept this key."))
    bad = client.put("/api/account/keys/groq", headers=headers, json={"key": "gsk_wrong_key_123"})
    assert bad.status_code == 400 and "did not accept" in bad.json()["detail"]
    saved = client.put("/api/account/keys/groq", headers=headers, json={"key": GROQ_KEY})
    assert saved.json()["keys"][0]["provider"] == "groq" and saved.json()["keys"][0]["last4"] == GROQ_KEY[-4:]
    stored = server.db.user_keys(user["id"])[0]["key_enc"]
    assert stored.startswith("g1:") and GROQ_KEY not in stored
    assert "key_enc" not in json.dumps(client.get("/api/account/keys", headers=headers).json())
    assert client.get("/api/account", headers=headers).json()["own_keys"] == {"server": ["groq"], "in_use": ["groq"]}
    assert client.delete("/api/account/keys/groq", headers=headers).json()["keys"] == []


def test_own_keys_replace_the_servers_and_follow_into_threads(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "server-groq-key-000")
    groq, gemini = llm_providers.REGISTRY["groq"], llm_providers.REGISTRY["gemini"]
    seen = {}

    def answer():
        llm_providers.use_keys({"groq": GROQ_KEY})
        assert groq.api_key == GROQ_KEY and gemini.api_key == ""  # never the server's key for another provider
        threading.Thread(target=llm_providers.carry(lambda: seen.update(carried=groq.api_key))).start()
        threading.Thread(target=lambda: seen.update(plain=groq.api_key)).start()
        with llm_providers.server_keys():
            seen["infrastructure"] = groq.api_key
    contextvars.copy_context().run(answer)
    import time
    time.sleep(0.2)
    assert seen == {"carried": GROQ_KEY, "plain": "server-groq-key-000", "infrastructure": "server-groq-key-000"}
    assert groq.api_key == "server-groq-key-000"  # outside the request, the server's own key


def test_one_users_rate_limit_does_not_slow_another(monkeypatch):
    groq = llm_providers.REGISTRY["groq"]

    def cool(key):
        llm_providers.use_keys({"groq": key})
        llm_providers._cool(groq, 60, "test")
        return llm_providers._available(groq, 10)[0]

    def available(key):
        llm_providers.use_keys({"groq": key})
        return llm_providers._available(groq, 10)[0]
    assert contextvars.copy_context().run(cool, "gsk_" + "a" * 30) is False
    assert contextvars.copy_context().run(available, "gsk_" + "b" * 30) is True


def test_keys_set_in_middleware_reach_a_streamed_answer():
    # The stream endpoint's generator runs after the endpoint returns, in Starlette's thread pool.
    var = contextvars.ContextVar("test_keys", default=None)
    app = FastAPI()

    @app.middleware("http")
    async def keys(request, call_next):
        var.set(request.headers.get("x-k"))
        return await call_next(request)

    @app.get("/s")
    def stream():
        def body():
            yield f"{var.get()}|"
            yield str(var.get())
        return StreamingResponse(body())
    c = TestClient(app)
    assert c.get("/s", headers={"x-k": "mine"}).text == "mine|mine"
    assert c.get("/s").text == "None|None"


def test_sessions_keep_a_device_label_and_no_ip_address(hosted):
    headers, user = sign_in(hosted, "minimal@example.com")
    rows = server.db.conn.execute("SELECT user_agent, ip FROM sessions WHERE user_id = ?", (user["id"],)).fetchall()
    assert rows and all(r["ip"] is None and r["user_agent"] == "Chrome on macOS" for r in rows)
    sessions = client.get("/api/account/sessions", headers=headers).json()["sessions"]
    assert sessions[0]["device"] == "Chrome on macOS" and "ip" not in sessions[0]
