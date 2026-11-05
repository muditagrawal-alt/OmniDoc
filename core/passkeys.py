"""
Passkeys (WebAuthn): sign up and sign in with Face ID, Touch ID, Windows Hello, a phone or a
security key. No password and no e-mail is involved; the server keeps only each passkey's public key.

Passkeys are discoverable credentials, so signing in needs no user name: the browser offers the
passkeys it holds for this site and the credential id says whose it is. Challenges are random,
single-use and expire after five minutes.

The relying party is the address users open (OMNIDOC_PUBLIC_URL, e.g. https://1-2-3-4.sslip.io).
WebAuthn does not accept an IP address as the site, so a local install served on 127.0.0.1 uses
"localhost" (open http://localhost:<port>); OMNIDOC_RP_ID overrides it.
"""
import os
import json
import time
import secrets
import ipaddress
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from webauthn import (
    generate_registration_options, verify_registration_response,
    generate_authentication_options, verify_authentication_response, options_to_json,
)
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
    ResidentKeyRequirement, UserVerificationRequirement,
)

from core import accounts

CHALLENGE_TTL_S = 300
RP_NAME = "OmniDoc"


class PasskeyError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    # An allow-list names e-mail addresses, which a passkey account does not have.
    return accounts.enabled() and os.getenv("OMNIDOC_PASSKEYS", "1") != "0" and not os.getenv("OMNIDOC_ALLOWED_EMAILS", "").strip()


def rp_id() -> str:
    explicit = os.getenv("OMNIDOC_RP_ID", "").strip()
    if explicit:
        return explicit
    host = urllib.parse.urlparse(accounts.public_url()).hostname or "localhost"
    try:
        ipaddress.ip_address(host)
        return "localhost"
    except ValueError:
        return host


def origins() -> List[str]:
    """The page origins a passkey ceremony may come from: the public address, plus local origins on this site."""
    found = [accounts.public_url()]
    extra = os.getenv("OMNIDOC_CORS_ORIGINS", "http://localhost:5173,http://localhost:4173,http://localhost:8000")
    site = rp_id()
    for origin in [o.strip().rstrip("/") for o in extra.split(",") if o.strip()]:
        host = urllib.parse.urlparse(origin).hostname or ""
        if (host == site or host.endswith("." + site)) and origin not in found:
            found.append(origin)
    return found


def _store_challenge(db: Any, purpose: str, challenge: bytes, user_id: Optional[str] = None,
                     data: Optional[Dict[str, Any]] = None) -> str:
    challenge_id = secrets.token_urlsafe(18)
    db.put_challenge(challenge_id, purpose, bytes_to_base64url(challenge), user_id, json.dumps(data or {}))
    return challenge_id


def _take_challenge(db: Any, challenge_id: str, purpose: str) -> Dict[str, Any]:
    row = db.take_challenge(challenge_id or "", purpose, CHALLENGE_TTL_S)
    if not row:
        raise PasskeyError("This request expired. Try again.")
    row["data"] = json.loads(row.get("data") or "{}")
    return row


def registration_options(db: Any, purpose: str, user_handle: bytes, name: str, user_id: Optional[str] = None,
                         exclude: Optional[List[str]] = None) -> Tuple[str, Dict[str, Any]]:
    """Options for navigator.credentials.create(): purpose "signup" (a new account) or "add" (another passkey)."""
    options = generate_registration_options(
        rp_id=rp_id(), rp_name=RP_NAME, user_id=user_handle, user_name=name, user_display_name=name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in (exclude or [])],
    )
    challenge_id = _store_challenge(db, purpose, options.challenge, user_id,
                                    {"handle": bytes_to_base64url(user_handle), "name": name})
    return challenge_id, json.loads(options_to_json(options))


def verify_registration(db: Any, challenge_id: str, purpose: str, credential: Dict[str, Any]) -> Dict[str, Any]:
    """Checks a new passkey; returns its id, public key and counter with the challenge's user and name."""
    row = _take_challenge(db, challenge_id, purpose)
    try:
        verified = verify_registration_response(
            credential=credential, expected_challenge=base64url_to_bytes(row["challenge"]),
            expected_rp_id=rp_id(), expected_origin=origins())
    except Exception as e:
        raise PasskeyError(f"The passkey could not be verified ({e}).")
    transports = (credential.get("response") or {}).get("transports") or []
    return {"credential_id": bytes_to_base64url(verified.credential_id),
            "public_key": bytes_to_base64url(verified.credential_public_key),
            "sign_count": verified.sign_count, "transports": ",".join(str(t) for t in transports)[:120],
            "user_id": row.get("user_id"), "handle": row["data"].get("handle"), "name": row["data"].get("name") or ""}


def authentication_options(db: Any) -> Tuple[str, Dict[str, Any]]:
    """Options for navigator.credentials.get() with no user named: any passkey for this site may answer."""
    options = generate_authentication_options(rp_id=rp_id(), user_verification=UserVerificationRequirement.PREFERRED)
    return _store_challenge(db, "signin", options.challenge), json.loads(options_to_json(options))


def verify_authentication(db: Any, challenge_id: str, credential: Dict[str, Any]) -> str:
    """The user id of the account whose passkey signed the challenge."""
    row = _take_challenge(db, challenge_id, "signin")
    stored = db.get_passkey(str(credential.get("id") or ""))
    if not stored:
        raise PasskeyError("This passkey is not registered here. It may have been removed from the account.", 401)
    try:
        verified = verify_authentication_response(
            credential=credential, expected_challenge=base64url_to_bytes(row["challenge"]),
            expected_rp_id=rp_id(), expected_origin=origins(),
            credential_public_key=base64url_to_bytes(stored["public_key"]),
            credential_current_sign_count=int(stored.get("sign_count") or 0))
    except Exception as e:
        raise PasskeyError(f"The passkey could not be verified ({e}).", 401)
    db.passkey_used(stored["id"], verified.new_sign_count, time.time())
    return stored["user_id"]


def new_user_handle() -> bytes:
    return secrets.token_bytes(32)
