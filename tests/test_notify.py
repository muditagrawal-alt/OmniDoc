"""
Feedback e-mails to the operator: what they contain, that visitors' text cannot change their
headers or markup, the hourly cap, and that SMTP for notices does not switch on e-mail sign-in.
"""
import threading

import httpx

from core import abuse, accounts, notify
from test_account_security import client, hosted, proof  # noqa: F401  (hosted is a fixture)


def _smtp(monkeypatch, sent):
    monkeypatch.setenv("OMNIDOC_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("OMNIDOC_SMTP_USER", "owner@example.com")
    monkeypatch.setenv("OMNIDOC_FEEDBACK_EMAIL", "owner@example.com")
    done = threading.Event()

    def fake_send(msg):
        sent.append(msg)
        done.set()

    monkeypatch.setattr(accounts, "smtp_send", fake_send)
    return done


def test_the_message_escapes_the_visitor_and_replies_only_to_an_address(monkeypatch):
    _smtp(monkeypatch, [])
    msg = notify.feedback_message({"rating": 4, "message": "<script>alert(1)</script>\nSecond line\r\nBcc: x@y.z",
                                   "contact": "asha@example.org", "created_at": 1793971200}, "https://omnidoc.example")
    assert "\n" not in msg["Subject"] and msg["Subject"].startswith("OmniDoc feedback · 4/5: ")
    assert msg["Reply-To"] == "asha@example.org" and msg["To"] == "owner@example.com" and msg["Bcc"] is None
    html_part = msg.get_body(("html",)).get_content()
    assert "<script>" not in html_part and "&lt;script&gt;" in html_part
    assert "https://omnidoc.example/#/admin" in msg.get_body(("plain",)).get_content()
    handle = notify.feedback_message({"message": "Nice", "contact": "@asha on GitHub"}, "https://omnidoc.example")
    assert handle["Reply-To"] is None and "@asha on GitHub" in handle.get_body(("plain",)).get_content()


def test_smtp_for_notices_does_not_open_email_sign_in(monkeypatch):
    monkeypatch.setenv("OMNIDOC_ACCOUNTS", "1")
    monkeypatch.delenv("OMNIDOC_OTP_LOG", raising=False)
    monkeypatch.setenv("OMNIDOC_SMTP_HOST", "smtp.example.com")
    assert accounts.email_configured() is True  # unchanged for servers that use it for sign-in
    monkeypatch.setenv("OMNIDOC_EMAIL_SIGNIN", "0")
    assert accounts.email_configured() is False and accounts.methods()["email"] is False


def test_feedback_is_mailed_in_the_background_and_capped(hosted, monkeypatch):
    sent = []
    done = _smtp(monkeypatch, sent)
    monkeypatch.setenv("OMNIDOC_FEEDBACK_EMAILS_PER_HOUR", "1")
    abuse.limiter.reset()
    r = client.post("/api/feedback", json={"message": "The viewer opened page 3", "rating": 5, "pow": proof()})
    assert r.status_code == 200
    assert done.wait(5) and "The viewer opened page 3" in sent[0].get_body(("plain",)).get_content()
    # Over the cap: kept for Admin, not mailed.
    assert client.post("/api/feedback", json={"message": "Second one", "pow": proof()}).status_code == 200
    assert len(sent) == 1
    abuse.limiter.reset()


def test_no_recipient_means_no_mail(monkeypatch):
    monkeypatch.delenv("OMNIDOC_FEEDBACK_EMAIL", raising=False)
    assert notify.notify_feedback({"message": "hi"}, "https://x") is False


def test_resend_is_used_when_its_key_is_set_and_the_key_stays_in_the_header(hosted, monkeypatch, caplog):
    key = "re_test_not_a_real_key_0123456789"
    monkeypatch.setenv("RESEND_API_KEY", key)
    monkeypatch.setenv("OMNIDOC_FEEDBACK_EMAIL", "owner@example.com")
    monkeypatch.setattr(accounts, "smtp_send", lambda msg: (_ for _ in ()).throw(AssertionError("SMTP used")))
    calls, done = [], threading.Event()

    class Reply:
        def __init__(self, status, body):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers))
        done.set()
        return Reply(200, {"id": "email_123"})

    monkeypatch.setattr(httpx, "post", fake_post)
    abuse.limiter.reset()
    r = client.post("/api/feedback", json={"message": "<b>Bold</b> claim", "rating": 2, "contact": "kavya@example.org", "pow": proof()})
    assert r.status_code == 200 and done.wait(5)
    url, payload, headers = calls[0]
    assert url == "https://api.resend.com/emails" and headers["Authorization"] == f"Bearer {key}"
    assert payload["from"] == "OmniDoc <onboarding@resend.dev>" and payload["to"] == ["owner@example.com"]
    assert payload["reply_to"] == "kavya@example.org" and "&lt;b&gt;Bold" in payload["html"]
    assert key not in str(payload)

    # A refusal is logged with Resend's reason, never with the key.
    done.clear()
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (done.set(), Reply(403, {"message": "You can only send testing emails to your own email address"}))[1])
    with caplog.at_level("WARNING", logger="OmniDoc.Notify"):
        assert client.post("/api/feedback", json={"message": "Second", "pow": proof()}).status_code == 200
        done.wait(5)
        for _ in range(50):
            if "Resend answered 403" in caplog.text:
                break
            threading.Event().wait(0.05)
    assert "Resend answered 403" in caplog.text and key not in caplog.text
    abuse.limiter.reset()
