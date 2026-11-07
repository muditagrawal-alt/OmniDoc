"""
Heavy traffic: the demo's repeated questions are answered from a cache without a model call, answers
wait for one of a few slots and are turned away clearly when none frees up, and the public sign-in
check can be kept by the CDN.
"""
import json
from types import SimpleNamespace

import server
from core import abuse, capacity
from test_account_security import client, hosted, proof  # noqa: F401  (hosted is a fixture)


class FakePipeline:
    def __init__(self):
        self.calls = 0

    def query_stream(self, **kw):
        self.calls += 1
        yield "step", {"node": "retrieve", "label": "Searching the documents", "detail": "", "duration_ms": 5}
        yield "delta", "Revenue was INR 1,284 crore."
        yield "result", {"draft_response": "Revenue was INR 1,284 crore."}


def _events(r):
    out = []
    for block in r.text.strip().split("\n\n"):
        kind = next((l[7:] for l in block.splitlines() if l.startswith("event: ")), None)
        data = next((l[6:] for l in block.splitlines() if l.startswith("data: ")), None)
        if kind:
            out.append((kind, json.loads(data) if data else None))
    return out


def _guest():
    r = client.post("/api/auth/guest", json={"pow": proof()})
    assert r.status_code == 200, r.text
    headers = {"X-OmniDoc-Token": r.json()["token"]}
    chat = client.post("/api/chats", headers=headers, json={"title": "Demo"}).json()["chat"]["id"]
    return headers, chat


def test_the_demo_answers_a_repeated_question_from_the_cache(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_DEMO", "1")
    fake = FakePipeline()
    monkeypatch.setattr(server, "get_pipeline", lambda: fake)
    capacity.DEMO_ANSWERS.clear()
    question = {"query": "What was Kestrel's revenue in FY2025?"}

    first_headers, first_chat = _guest()
    first = _events(client.post(f"/api/chats/{first_chat}/query/stream", headers=first_headers, json=question))
    assert fake.calls == 1 and first[-1][0] == "result"

    abuse.limiter.reset()
    again_headers, again_chat = _guest()
    used_before = server.db.trial_used(client.get("/api/auth/me", headers=again_headers).json()["user"]["id"])
    again = _events(client.post(f"/api/chats/{again_chat}/query/stream", headers=again_headers,
                                json={"query": "  what was Kestrel's revenue in FY2025  "}))
    assert fake.calls == 1  # no model call: replayed
    assert [k for k, _ in again] == [k for k, _ in first]
    assert again[-1][1]["answer"] == "Revenue was INR 1,284 crore." and again[-1][1]["message_id"]
    me = client.get("/api/auth/me", headers=again_headers).json()["user"]["id"]
    assert server.db.trial_used(me) == used_before  # a replay is not a free answer used
    assert len(client.get(f"/api/chats/{again_chat}", headers=again_headers).json()["messages"]) == 2

    # A different question, or a signed-in account, is never served from the cache.
    _events(client.post(f"/api/chats/{again_chat}/query/stream", headers=again_headers, json={"query": "And the margin?"}))
    assert fake.calls == 2
    capacity.DEMO_ANSWERS.clear()
    abuse.limiter.reset()


def test_answers_wait_for_a_slot_and_are_turned_away_when_none_frees(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_DEMO", "1")
    monkeypatch.setenv("OMNIDOC_QUEUE_SECONDS", "0.2")
    monkeypatch.setattr(server, "get_pipeline", lambda: FakePipeline())
    capacity.DEMO_ANSWERS.clear()
    full = capacity.Slots("answers", 1)
    assert full.acquire(0)
    monkeypatch.setattr(capacity, "ANSWERS", full)
    headers, chat = _guest()
    streamed = _events(client.post(f"/api/chats/{chat}/query/stream", headers=headers, json={"query": "Busy?"}))
    assert streamed[0][1]["label"] == "Waiting for a free moment"
    assert streamed[-1][0] == "error" and "try again" in streamed[-1][1]["message"]
    r = client.post("/api/query", headers=headers, json={"query": "Busy?"})
    assert r.status_code == 503 and r.headers["retry-after"] == "30"
    full.release()
    assert _events(client.post(f"/api/chats/{chat}/query/stream", headers=headers, json={"query": "Free now?"}))[-1][0] == "result"
    assert full.active == 0  # the slot is given back after the answer
    abuse.limiter.reset()


def test_the_public_sign_in_check_is_cacheable(hosted):
    r = client.get("/api/auth/methods")
    assert r.status_code == 200 and "s-maxage" in r.headers["cache-control"] and "public" in r.headers["cache-control"]
    assert client.get("/api/health").headers["cache-control"] == "no-store"
