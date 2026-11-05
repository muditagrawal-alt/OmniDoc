"""
Two-step sign-in without e-mail: authenticator apps (TOTP) and one-time recovery codes.

* TOTP (RFC 6238): any authenticator app (Google or Microsoft Authenticator, 1Password, Authy...)
  scans a QR code once and then shows a new six-digit code every 30 seconds. The secret is stored
  encrypted with the server key; a code is accepted once (no replay) and one step either side of now.
* Recovery codes: ten one-time codes shown once. Each is 12 characters from an alphabet without
  look-alike characters (about 59 bits), so a code also identifies its account: it signs in a user
  who lost every passkey, or replaces the authenticator code. Only keyed hashes are stored.
* After GitHub, Google or an e-mailed code, an account with TOTP gets a five-minute ticket instead of
  a session; the ticket plus a current code (or a recovery code) makes the session. Five tries.
"""
import io
import re
import time
import secrets
from pathlib import Path
from typing import Any, List, Optional

import pyotp

from core import accounts

ISSUER = "OmniDoc"
RECOVERY_CODES = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
TICKET_TTL_S = 300
TICKET_TRIES = 5


class TwoFactorError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------- TOTP
def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, label: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=label or "account", issuer_name=ISSUER)


def qr_svg(uri: str) -> str:
    """The QR code an authenticator app scans, as an SVG (dark modules, transparent ground)."""
    import segno
    out = io.BytesIO()
    segno.make(uri, error="m").save(out, kind="svg", scale=5, border=2, dark="#121620", light=None,
                                  xmldecl=False, omitsize=True)  # a viewBox, so it scales to its box
    return out.getvalue().decode("utf-8")


def check_totp(secret: str, code: str, last_step: int) -> Optional[int]:
    """The time step of a valid, unused code, or None."""
    code = re.sub(r"\D", "", code or "")
    if len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now = time.time()
    for offset in (0, -1, 1):
        at = now + offset * totp.interval
        step = int(at // totp.interval)
        if step > (last_step or 0) and secrets.compare_digest(totp.at(at), code):
            return step
    return None


# ------------------------------------------------------------ recovery codes
def normalize_recovery(code: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (code or "").lower())


def recovery_hash(data_dir: Path, code: str) -> str:
    return accounts.keyed_hash(data_dir, "recovery", normalize_recovery(code))


def new_recovery_codes(db: Any, data_dir: Path, user_id: str) -> List[str]:
    """Replaces the account's recovery codes with ten new ones and returns them (shown once)."""
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    db.replace_recovery_codes(user_id, [recovery_hash(data_dir, c) for c in codes])
    return codes


def use_recovery_code(db: Any, data_dir: Path, code: str, user_id: Optional[str] = None) -> Optional[str]:
    """Spends a recovery code (optionally only one of user_id's) and returns its account, or None."""
    if len(normalize_recovery(code)) != 12:
        return None
    return db.spend_recovery_code(recovery_hash(data_dir, code), user_id, time.time())


# ------------------------------------------------------------------- tickets
def issue_ticket(db: Any, data_dir: Path, user_id: str, method: str) -> str:
    ticket = secrets.token_urlsafe(24)
    db.put_mfa_ticket(accounts.keyed_hash(data_dir, "mfa", ticket), user_id, method)
    return ticket


def redeem_ticket(db: Any, data_dir: Path, ticket: str, code: str) -> str:
    """The user id behind a ticket once a current authenticator code or a recovery code is given."""
    key = accounts.keyed_hash(data_dir, "mfa", ticket or "")
    row = db.get_mfa_ticket(key)
    if not row or time.time() - row["created_at"] > TICKET_TTL_S:
        raise TwoFactorError("The sign-in took too long. Start again.", 401)
    if row["attempts"] >= TICKET_TRIES:
        raise TwoFactorError("Too many wrong codes. Start again.", 429)
    db.mfa_attempt(key)
    user = db.get_user(row["user_id"]) or {}
    secret = accounts.decrypt(data_dir, user.get("totp_secret") or "")
    step = check_totp(secret, code, int(user.get("totp_last_step") or 0)) if secret else None
    if step is not None:
        db.set_totp_step(user["id"], step)
    elif not use_recovery_code(db, data_dir, code, user_id=row["user_id"]):
        left = TICKET_TRIES - row["attempts"] - 1
        raise TwoFactorError(f"That code is not right. {left} {'try' if left == 1 else 'tries'} left." if left > 0
                             else "Too many wrong codes. Start again.", 401)
    db.delete_mfa_ticket(key)
    return row["user_id"]
