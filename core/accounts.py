"""
Accounts for a hosted OmniDoc: sign-in with an e-mailed one-time code, Google or GitHub, and the
limits that keep free model quotas and the server's disk shared fairly.

Turned on with OMNIDOC_ACCOUNTS=1. Without it OmniDoc stays a single-user app on your machine
(every request acts as the local profile), exactly as before.

* E-mail codes: six digits, valid for 10 minutes and for 5 tries, sent by any SMTP service
  (OMNIDOC_SMTP_*; free options include Gmail with an app password and Brevo). Only an HMAC of
  each code is stored, at most one code a minute and 6 an hour go to an address, and the reply
  never says whether an address has an account.
* Google and GitHub: the standard OAuth 2.0 authorization-code flow with a one-time state. Only
  a verified e-mail address signs in; the same address is the same account whichever way it signs in.
* Optional allow-list (OMNIDOC_ALLOWED_EMAILS: addresses or @domains) and admins
  (OMNIDOC_ADMIN_EMAILS), who have no limits and may change the server's model.
* Daily limits per account on questions and uploads, and a storage cap.
"""
import os
import re
import hmac
import time
import secrets
import hashlib
import logging
import smtplib
import urllib.parse
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("OmniDoc.Accounts")

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")
CODE_TTL_S = 600
CODE_TRIES = 5
CODE_GAP_S = 60
CODES_PER_HOUR = 6
SESSION_DAYS = float(os.getenv("OMNIDOC_SESSION_DAYS", "30"))


def enabled() -> bool:
    return os.getenv("OMNIDOC_ACCOUNTS", "0") == "1"


def _env_list(name: str) -> List[str]:
    return [x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip()]


def public_url() -> str:
    """The address users open (redirects after Google and GitHub sign-in come back here)."""
    return os.getenv("OMNIDOC_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")


# ------------------------------------------------------------------- limits
def limits() -> Dict[str, int]:
    return {
        "questions_per_day": int(os.getenv("OMNIDOC_DAILY_QUESTIONS", "40")),
        "uploads_per_day": int(os.getenv("OMNIDOC_DAILY_UPLOADS", "20")),
        "storage_mb": int(os.getenv("OMNIDOC_STORAGE_MB", "200")),
    }


def is_admin(email: Optional[str]) -> bool:
    return bool(email) and email.lower() in _env_list("OMNIDOC_ADMIN_EMAILS")


def allowed(email: str) -> bool:
    """Whether an address may sign in: everyone, or the listed addresses and @domains."""
    rules = _env_list("OMNIDOC_ALLOWED_EMAILS")
    if not rules:
        return True
    email = email.lower()
    return any(email == r or (r.startswith("@") and email.endswith(r)) for r in rules) or is_admin(email)


def normalize_email(email: str) -> Optional[str]:
    email = (email or "").strip().lower()
    return email if EMAIL_RE.match(email) else None


# ------------------------------------------------------------------- secrets
def _secret(data_dir: Path) -> bytes:
    """OMNIDOC_SECRET_KEY, else a random key kept in the data folder (readable by the owner only)."""
    explicit = os.getenv("OMNIDOC_SECRET_KEY", "").strip()
    if explicit:
        return explicit.encode("utf-8")
    path = Path(data_dir) / "secret.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return path.read_text().strip().encode("utf-8")


def keyed_hash(data_dir: Path, *parts: str) -> str:
    return hmac.new(_secret(data_dir), "\x00".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


# --------------------------------------------------------------- e-mail codes
def email_configured() -> bool:
    return bool(os.getenv("OMNIDOC_SMTP_HOST")) or os.getenv("OMNIDOC_OTP_LOG", "0") == "1"


def send_code_email(to: str, code: str) -> None:
    """Sends the sign-in code by SMTP; with OMNIDOC_OTP_LOG=1 and no SMTP it is only logged (local testing)."""
    host = os.getenv("OMNIDOC_SMTP_HOST", "").strip()
    if not host:
        if os.getenv("OMNIDOC_OTP_LOG", "0") == "1":
            logger.warning(f"Sign-in code for {to}: {code} (OMNIDOC_OTP_LOG=1; set OMNIDOC_SMTP_HOST to e-mail it)")
            return
        raise RuntimeError("E-mail sign-in is not configured")
    port = int(os.getenv("OMNIDOC_SMTP_PORT", "587"))
    user = os.getenv("OMNIDOC_SMTP_USER", "")
    password = os.getenv("OMNIDOC_SMTP_PASSWORD", "")
    sender = os.getenv("OMNIDOC_SMTP_FROM", user or f"OmniDoc <no-reply@{host}>")
    msg = EmailMessage()
    msg["Subject"] = f"{code} is your OmniDoc sign-in code"
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(
        f"Your OmniDoc sign-in code is {code}\n\n"
        f"It works once and expires in {CODE_TTL_S // 60} minutes. If you did not try to sign in, ignore this e-mail.\n")
    msg.add_alternative(f"""\
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:460px;margin:0 auto;padding:28px;color:#121620">
  <p style="font-size:15px;margin:0 0 18px">Your OmniDoc sign-in code:</p>
  <p style="font-size:32px;font-weight:600;letter-spacing:6px;margin:0 0 18px;font-family:Menlo,Consolas,monospace">{code}</p>
  <p style="font-size:13px;color:#4a5263;margin:0">It works once and expires in {CODE_TTL_S // 60} minutes.
  If you did not try to sign in, ignore this e-mail.</p>
</div>""", subtype="html")
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20) as s:
            if user:
                s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            if user:
                s.login(user, password)
            s.send_message(msg)


class CodeError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def request_code(db: Any, data_dir: Path, email: str) -> None:
    """Creates and sends a code (the caller replies the same way whether or not the address has an account)."""
    now = time.time()
    current = db.get_otp(email) or {}
    if now - (current.get("last_sent") or 0) < CODE_GAP_S:
        raise CodeError("A code was sent less than a minute ago. Check your inbox, or try again shortly.", 429)
    window_start, sends = current.get("window_start") or now, current.get("sends") or 0
    if now - window_start > 3600:
        window_start, sends = now, 0
    if sends >= CODES_PER_HOUR:
        raise CodeError("Too many codes were requested for this address. Try again in an hour.", 429)
    code = f"{secrets.randbelow(1_000_000):06d}"
    send_code_email(email, code)
    db.put_otp(email, keyed_hash(data_dir, "otp", email, code), now + CODE_TTL_S, sends + 1, window_start)


def verify_code(db: Any, data_dir: Path, email: str, code: str) -> None:
    """Raises CodeError unless the code is the address's current one; a correct code works once."""
    row = db.get_otp(email)
    code = re.sub(r"\D", "", code or "")
    if not row or not row.get("code_hash") or row["expires_at"] < time.time():
        raise CodeError("This code has expired. Request a new one.")
    if row["attempts"] >= CODE_TRIES:
        raise CodeError("Too many wrong codes. Request a new one.", 429)
    db.otp_attempt(email)
    if len(code) != 6 or not hmac.compare_digest(row["code_hash"], keyed_hash(data_dir, "otp", email, code)):
        left = CODE_TRIES - row["attempts"] - 1
        raise CodeError(f"That code is not right. {left} {'try' if left == 1 else 'tries'} left." if left > 0
                        else "Too many wrong codes. Request a new one.")
    db.otp_used(email)


# -------------------------------------------------------------------- OAuth
PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
    },
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
    },
}


def oauth_credentials(provider: str) -> Optional[Dict[str, str]]:
    key = provider.upper()
    cid, secret = os.getenv(f"OMNIDOC_{key}_CLIENT_ID", "").strip(), os.getenv(f"OMNIDOC_{key}_CLIENT_SECRET", "").strip()
    return {"id": cid, "secret": secret} if provider in PROVIDERS and cid and secret else None


def redirect_uri(provider: str) -> str:
    return f"{public_url()}/api/auth/oauth/{provider}/callback"


def methods() -> Dict[str, Any]:
    return {"accounts": enabled(), "email": enabled() and email_configured(),
            "google": enabled() and bool(oauth_credentials("google")),
            "github": enabled() and bool(oauth_credentials("github"))}


def authorize_url(db: Any, data_dir: Path, provider: str) -> str:
    creds = oauth_credentials(provider)
    if not creds:
        raise CodeError("This sign-in method is not configured.", 404)
    state = secrets.token_urlsafe(24)
    db.put_oauth_state(keyed_hash(data_dir, "oauth", state), provider)
    params = {"client_id": creds["id"], "redirect_uri": redirect_uri(provider), "scope": PROVIDERS[provider]["scope"],
              "state": state, "response_type": "code"}
    if provider == "google":
        params["prompt"] = "select_account"
    return PROVIDERS[provider]["authorize"] + "?" + urllib.parse.urlencode(params)


def oauth_identity(db: Any, data_dir: Path, provider: str, code: str, state: str) -> Dict[str, str]:
    """Exchanges the authorization code and returns the verified e-mail, name and avatar."""
    import httpx
    creds = oauth_credentials(provider)
    if not creds:
        raise CodeError("This sign-in method is not configured.", 404)
    if not state or not db.take_oauth_state(keyed_hash(data_dir, "oauth", state), provider):
        raise CodeError("The sign-in link expired. Try again.")
    token_resp = httpx.post(PROVIDERS[provider]["token"], headers={"Accept": "application/json"}, timeout=20, data={
        "client_id": creds["id"], "client_secret": creds["secret"], "code": code,
        "redirect_uri": redirect_uri(provider), "grant_type": "authorization_code"})
    access = (token_resp.json() if token_resp.status_code == 200 else {}).get("access_token")
    if not access:
        raise CodeError("The sign-in was not completed. Try again.")
    headers = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
    if provider == "google":
        info = httpx.get("https://openidconnect.googleapis.com/v1/userinfo", headers=headers, timeout=20).json()
        if not info.get("email") or not info.get("email_verified"):
            raise CodeError("Your Google account has no verified e-mail address.")
        return {"email": info["email"], "name": info.get("name") or "", "avatar_url": info.get("picture") or ""}
    user = httpx.get("https://api.github.com/user", headers=headers, timeout=20).json()
    emails = httpx.get("https://api.github.com/user/emails", headers=headers, timeout=20).json()
    verified = [e for e in emails if isinstance(e, dict) and e.get("verified") and e.get("email")] if isinstance(emails, list) else []
    primary = next((e["email"] for e in verified if e.get("primary")), verified[0]["email"] if verified else None)
    if not primary:
        raise CodeError("Your GitHub account has no verified e-mail address.")
    return {"email": primary, "name": user.get("name") or user.get("login") or "", "avatar_url": user.get("avatar_url") or ""}
