"""
Notices to the server's operator: an e-mail for every piece of feedback sent from the product page.

Set OMNIDOC_FEEDBACK_EMAIL to the address that should receive them, and either:

* RESEND_API_KEY (or OMNIDOC_RESEND_API_KEY): Resend's HTTP API, free for 3,000 e-mails a month.
  Without a domain of your own, mail comes from onboarding@resend.dev and Resend only delivers it
  to the address the Resend account was made with, which is exactly the operator's own inbox.
  OMNIDOC_RESEND_FROM sets another sender once a domain is verified there. Preferred when set.
* OMNIDOC_SMTP_*: any SMTP service (Gmail with an app password is free).

Mail goes out on a background thread, so sending feedback never waits for it, and at most
OMNIDOC_FEEDBACK_EMAILS_PER_HOUR (default 30) are sent, so a flood of feedback cannot exhaust the
sending quota; everything is still kept for the Admin tab. Whatever the visitor typed is escaped,
and only goes in the Reply-To header when it is a plain e-mail address. The API key is sent only in
the Authorization header of the request to Resend and is never logged.
"""
import html
import logging
import os
import re
import threading
import time
from email.message import EmailMessage
from typing import Any, Dict, Optional

from core import abuse, accounts

logger = logging.getLogger("OmniDoc.Notify")

RESEND_URL = "https://api.resend.com/emails"
_ADDRESS = re.compile(r"^[^@\s<>,;\"']{1,64}@[^@\s<>,;\"']{1,190}\.[A-Za-z]{2,24}$")
_STARS = {1: "1/5 · not useful", 2: "2/5 · rough", 3: "3/5 · okay", 4: "4/5 · good", 5: "5/5 · very useful"}


def feedback_recipient() -> str:
    return os.getenv("OMNIDOC_FEEDBACK_EMAIL", "").strip()


def resend_key() -> str:
    return (os.getenv("OMNIDOC_RESEND_API_KEY") or os.getenv("RESEND_API_KEY") or "").strip()


def feedback_mail_enabled() -> bool:
    return bool(feedback_recipient()) and (bool(resend_key()) or accounts.smtp_configured())


def feedback_parts(item: Dict[str, Any], site: str) -> Dict[str, Any]:
    """Subject, plain text, HTML and Reply-To of the e-mail for one piece of feedback."""
    rating: Optional[int] = item.get("rating")
    message = str(item.get("message") or "")
    contact = str(item.get("contact") or "").strip()
    when = time.strftime("%d %b %Y, %H:%M UTC", time.gmtime(item.get("created_at") or time.time()))
    first_line = " ".join(message.split())[:60]
    admin = f"{site.rstrip('/')}/#/admin"
    rating_text = _STARS.get(rating, "none given") if rating else "none given"
    text = "\n".join([f"Rating: {rating_text}", f"Reply to: {contact or 'no contact left'}", f"Sent: {when}", "",
                      message, "", f"Every piece of feedback: {admin}"]) + "\n"
    body = f"""\
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#121620">
  <p style="font-size:13px;color:#4a5263;margin:0 0 6px">New feedback on OmniDoc · {html.escape(when)}</p>
  <p style="font-size:15px;margin:0 0 16px"><strong>Rating:</strong> {html.escape(rating_text)}
    &nbsp;·&nbsp; <strong>Reply to:</strong> {html.escape(contact) or 'no contact left'}</p>
  <div style="font-size:15px;line-height:1.55;white-space:pre-wrap;padding:14px 16px;border-radius:10px;background:#f4f5f8">{html.escape(message)}</div>
  <p style="font-size:13px;margin:18px 0 0"><a href="{html.escape(admin)}" style="color:#0f62fe">Every piece of feedback, in the Admin tab</a></p>
</div>"""
    return {
        "subject": f"OmniDoc feedback{' · ' + str(rating) + '/5' if rating else ''}: {first_line}",
        "text": text,
        "html": body,
        "reply_to": contact if _ADDRESS.match(contact) else None,
    }


def feedback_message(item: Dict[str, Any], site: str) -> EmailMessage:
    """The feedback as an e-mail message, for SMTP."""
    parts = feedback_parts(item, site)
    msg = EmailMessage()
    msg["Subject"] = parts["subject"]
    msg["From"] = accounts.smtp_sender()
    msg["To"] = feedback_recipient()
    if parts["reply_to"]:
        msg["Reply-To"] = parts["reply_to"]
    msg.set_content(parts["text"])
    msg.add_alternative(parts["html"], subtype="html")
    return msg


def resend_payload(item: Dict[str, Any], site: str) -> Dict[str, Any]:
    """The feedback as the JSON body of Resend's send-email request."""
    parts = feedback_parts(item, site)
    payload = {
        "from": os.getenv("OMNIDOC_RESEND_FROM", "").strip() or "OmniDoc <onboarding@resend.dev>",
        "to": [feedback_recipient()],
        "subject": parts["subject"],
        "text": parts["text"],
        "html": parts["html"],
    }
    if parts["reply_to"]:
        payload["reply_to"] = parts["reply_to"]
    return payload


def send_with_resend(payload: Dict[str, Any]) -> None:
    import httpx
    r = httpx.post(RESEND_URL, json=payload, timeout=20,
                   headers={"Authorization": f"Bearer {resend_key()}", "User-Agent": "OmniDoc"})
    if r.status_code >= 300:
        try:
            reason = str(r.json().get("message") or "")[:200]
        except ValueError:
            reason = ""
        raise RuntimeError(f"Resend answered {r.status_code}{': ' + reason if reason else ''}")


def notify_feedback(item: Dict[str, Any], site: str) -> bool:
    """Sends the feedback e-mail in the background. False when it is off or over the hourly cap."""
    if not feedback_mail_enabled():
        return False
    cap = max(1, int(os.getenv("OMNIDOC_FEEDBACK_EMAILS_PER_HOUR", "30")))
    if abuse.limiter.hit("feedback-mail", cap, 3600):
        logger.warning("Feedback e-mail skipped: more than %s this hour (the feedback is kept in Admin).", cap)
        return False
    if resend_key():
        payload = resend_payload(item, site)
        deliver, how = (lambda: send_with_resend(payload)), "Resend"
    else:
        msg = feedback_message(item, site)
        deliver, how = (lambda: accounts.smtp_send(msg)), "SMTP"

    def send() -> None:
        try:
            deliver()
            logger.info("Feedback e-mailed to the operator (%s).", how)
        except Exception as exc:  # noqa: BLE001 (a mail problem must never affect the visitor)
            logger.warning("Could not e-mail the feedback (%s): %s", how, exc)

    threading.Thread(target=send, name="feedback-mail", daemon=True).start()
    return True
