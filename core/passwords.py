"""
Password sign-in for a hosted OmniDoc, as an alternative to passkeys.

Passwords are stored as scrypt hashes (N=2^15, r=8, p=1: 32 MB and about 50 ms each, a deliberate
cost for anyone trying guesses offline), never in a form that can be reversed. A password must have
at least ten characters and may not be one of the most common passwords or the username itself
(NIST SP 800-63B: length and a deny-list, no composition rules).

There is no e-mail, so "forgot password" is answered by the account's one-time recovery codes,
given at sign-up: a code and a new password reset it.
"""
import base64
import hmac
import os
import re
from typing import Optional

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

N, R, P = 2 ** 15, 8, 1
MIN_LENGTH = 10
MAX_LENGTH = 200
USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")

# The most common passwords of at least ten characters in public breach lists (shorter ones fail on length).
COMMON = {
    "1234567890", "0123456789", "1q2w3e4r5t", "qwertyuiop", "password12", "password123", "password1234",
    "iloveyou12", "qwerty1234", "1qaz2wsx3edc", "123456789a", "abcdefghij", "a1234567890", "passw0rd12",
    "welcome123", "letmein123", "football12", "baseball12", "superman12", "princess12", "sunshine12",
    "1111111111", "0000000000", "9876543210", "qwerty12345", "asdfghjkl1", "zxcvbnm123", "dragon1234",
    "monkey1234", "admin12345", "administrator", "changeme123", "trustno123", "omnidoc123", "omnidoc1234",
}

_DUMMY: Optional[str] = None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def clean_username(value: str) -> str:
    return (value or "").strip().lower()


def username_problem(username: str) -> Optional[str]:
    if not USERNAME.match(username):
        return "Use 3 to 32 letters, digits, dots, dashes or underscores, starting with a letter or digit."
    return None


def password_problem(password: str, username: str = "") -> Optional[str]:
    """Why a new password is refused, or None when it is fine."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters. A few words in a row are easy to remember and hard to guess."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    lowered = password.lower()
    if lowered in COMMON or len(set(password)) < 4:
        return "That password is one of the most common ones. Choose another."
    if username and username in lowered:
        return "The password should not contain your username."
    return None


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    """Whether the password matches; takes as long for an unknown account as for a known one."""
    global _DUMMY
    if not stored:
        _DUMMY = _DUMMY or hash_password("not-a-real-password")
        stored = _DUMMY
        password = password + "\0"  # never matches the dummy
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        return hmac.compare_digest(_derive(password, _unb64(salt), int(n), int(r), int(p)), _unb64(digest))
    except (ValueError, TypeError):
        return False
