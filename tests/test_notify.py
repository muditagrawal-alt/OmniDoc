"""
Feedback e-mails to the operator: what they contain, that visitors' text cannot change their
headers or markup, the hourly cap, and that SMTP for notices does not switch on e-mail sign-in.
"""
import threading

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
