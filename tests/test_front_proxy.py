"""
A front end on another host (Vercel) forwarding /api to this server under a secret prefix: the
prefix is removed, the visitor's address comes from the front end's header, and nothing else is
believed.
"""
import server
from core import abuse, proxy
from test_account_security import client, hosted  # noqa: F401  (hosted is a fixture)

KEY = "k3y-for-tests-0123456789abcdef"


def test_the_prefix_needs_the_right_key():
    assert proxy.split(f"/_via/{KEY}/api/health", KEY) == "/api/health"
    assert proxy.split("/_via/wrong/api/health", KEY) is None
    assert proxy.split(f"/_via/{KEY}/api/health", "") is None  # no key set: no front end
    assert proxy.split("/api/health", KEY) is None


def test_requests_through_the_front_end_are_routed_and_marked_private(monkeypatch):
    monkeypatch.setenv("OMNIDOC_PROXY_KEY", KEY)
    through = client.get(f"/_via/{KEY}/api/health")
    assert through.status_code == 200 and through.json()["status"]
    assert "private" in through.headers["cache-control"]
    assert client.get("/_via/not-the-key/api/health").status_code == 404
    assert "cache-control" not in client.get("/api/health").headers  # direct requests are unchanged


def test_limits_count_the_visitor_not_the_front_end(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_PROXY_KEY", KEY)
    monkeypatch.setattr(server, "API_PER_MINUTE", 3)
    abuse.limiter.reset()
    path = f"/_via/{KEY}/api/auth/methods"
    for _ in range(3):
        assert client.get(path, headers={"x-vercel-forwarded-for": "203.0.113.7"}).status_code == 200
    assert client.get(path, headers={"x-vercel-forwarded-for": "203.0.113.7"}).status_code == 429
    assert client.get(path, headers={"x-vercel-forwarded-for": "198.51.100.4"}).status_code == 200  # another visitor
    # Without the prefix, a visitor cannot choose their address with the same header.
    abuse.limiter.reset()
    for i in range(3):
        assert client.get("/api/auth/methods", headers={"x-vercel-forwarded-for": f"192.0.2.{i}"}).status_code == 200
    assert client.get("/api/auth/methods", headers={"x-vercel-forwarded-for": "192.0.2.99"}).status_code == 429
    abuse.limiter.reset()
