"""
Notices to the server's operator: an e-mail for every piece of feedback sent from the product page.

Set OMNIDOC_FEEDBACK_EMAIL to the address that should receive them, and OMNIDOC_SMTP_* to any SMTP
service (Gmail with an app password is free). Mail goes out on a background thread, so sending
feedback never waits for it, and at most OMNIDOC_FEEDBACK_EMAILS_PER_HOUR (default 30) are sent,
so a flood of feedback cannot exhaust the mailbox's sending quota; everything is still kept for
the Admin tab. Whatever the visitor typed is escaped, and only goes in the Reply-To header when it
is a plain e-mail address.
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

_ADDRESS = re.compile(r"^[^@\s<>,;\"']{1,64}@[^@\s<>,;\"']{1,190}\.[A-Za-z]{2,24}$")
_STARS = {1: "1/5 · not useful", 2: "2/5 · rough", 3: "3/5 · okay", 4: "4/5 · good", 5: "5/5 · very useful"}


def feedback_recipient() -> str:
    return os.getenv("OMNIDOC_FEEDBACK_EMAIL", "").strip()


def feedback_mail_enabled() -> bool:
    return bool(feedback_recipient()) and accounts.smtp_configured()


def feedback_message(item: Dict[str, Any], site: str) -> EmailMessage:
    """The e-mail for one piece of feedback (built separately so it can be tested without sending)."""
    rating: Optional[int] = item.get("rating")
    message = str(item.get("message") or "")
    contact = str(item.get("contact") or "").strip()
    when = time.strftime("%d %b %Y, %H:%M UTC", time.gmtime(item.get("created_at") or time.time()))
    first_line = " ".join(message.split())[:60]
    msg = EmailMessage()
    msg["Subject"] = f"OmniDoc feedback{' · ' + str(rating) + '/5' if rating else ''}: {first_line}"
    msg["From"] = accounts.smtp_sender()
    msg["To"] = feedback_recipient()
    if _ADDRESS.match(contact):
        msg["Reply-To"] = contact
    admin = f"{site.rstrip('/')}/#/admin"
    lines = [f"Rating: {_STARS.get(rating, 'none given')}" if rating else "Rating: none given",
             f"Reply to: {contact or 'no contact left'}", f"Sent: {when}", "", message, "", f"Every piece of feedback: {admin}"]
    msg.set_content("\n".join(lines) + "\n")
    rating_html = html.escape(_STARS.get(rating, "none given")) if rating else "none given"
    msg.add_alternative(f"""\
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#121620">
  <p style="font-size:13px;color:#4a5263;margin:0 0 6px">New feedback on OmniDoc · {html.escape(when)}</p>
  <p style="font-size:15px;margin:0 0 16px"><strong>Rating:</strong> {rating_html}
    &nbsp;·&nbsp; <strong>Reply to:</strong> {html.escape(contact) or 'no contact left'}</p>
  <div style="font-size:15px;line-height:1.55;white-space:pre-wrap;padding:14px 16px;border-radius:10px;background:#f4f5f8">{html.escape(message)}</div>
  <p style="font-size:13px;margin:18px 0 0"><a href="{html.escape(admin)}" style="color:#0f62fe">Every piece of feedback, in the Admin tab</a></p>
</div>""", subtype="html")
    return msg


def notify_feedback(item: Dict[str, Any], site: str) -> bool:
    """Sends the feedback e-mail in the background. False when it is off or over the hourly cap."""
    if not feedback_mail_enabled():
        return False
    cap = max(1, int(os.getenv("OMNIDOC_FEEDBACK_EMAILS_PER_HOUR", "30")))
    if abuse.limiter.hit("feedback-mail", cap, 3600):
        logger.warning("Feedback e-mail skipped: more than %s this hour (the feedback is kept in Admin).", cap)
        return False
    msg = feedback_message(item, site)

    def send() -> None:
        try:
            accounts.smtp_send(msg)
        except Exception as exc:  # noqa: BLE001 (a mail problem must never affect the visitor)
            logger.warning("Could not e-mail the feedback: %s", exc)

    threading.Thread(target=send, name="feedback-mail", daemon=True).start()
    return True
