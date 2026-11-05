"""
Abuse protection for a public OmniDoc, with no third-party service.

* client_ip: the visitor's address. X-Forwarded-For is believed only when the request came from a
  proxy on a private network or this machine (Caddy in docker-compose), and then only its last
  entry, the one that proxy added.
* RateLimiter: sliding-window limits per key (an address, an account), kept in memory: the server
  is one process.
* Proof of work: before creating an account, a guest session or using a recovery code, the browser
  finds the number whose SHA-256 matches a server challenge. That is about a second for a person
  and expensive for a bot making thousands of requests. The protocol is ALTCHA's: challenges are
  HMAC-signed, expire after five minutes and work once.
"""
import os
import hmac
import time
import secrets
import hashlib
import ipaddress
import threading
from collections import deque
from typing import Any, Deque, Dict, Optional, Tuple

POW_TTL_S = 300


def _difficulty() -> int:
    return max(1, int(os.getenv("OMNIDOC_POW_MAX", "80000")))


# Where a proxy in front of OmniDoc can be: this machine or a private (Docker) network. Spelled out,
# because ipaddress's is_private also counts the documentation ranges, which are public addresses here.
_PROXY_NETWORKS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")]


def client_ip(peer: Optional[str], forwarded_for: Optional[str]) -> str:
    peer = peer or ""
    try:
        address = ipaddress.ip_address(peer)
        trusted = any(address in net for net in _PROXY_NETWORKS if net.version == address.version)
    except ValueError:
        trusted = False
    if trusted and forwarded_for:
        last = forwarded_for.split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(last))
        except ValueError:
            pass
    return peer or "unknown"


class RateLimiter:
    """hit(key, limit, window) counts a request and says how long to wait when the key is over its limit."""

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float) -> Optional[float]:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, q[0] + window_s - now)
            q.append(now)
            if len(self._hits) > 50_000:  # forget idle keys so memory stays bounded
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - 86400][:10_000]:
                    self._hits.pop(k, None)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


# ------------------------------------------------------------- proof of work
_spent: Dict[str, float] = {}
_spent_lock = threading.Lock()


def _sign(key: bytes, challenge: str) -> str:
    return hmac.new(key, challenge.encode("ascii"), hashlib.sha256).hexdigest()


def new_challenge(key: bytes) -> Dict[str, Any]:
    expires = int(time.time()) + POW_TTL_S
    salt = f"{secrets.token_hex(12)}?expires={expires}"
    number = secrets.randbelow(_difficulty())
    challenge = hashlib.sha256(f"{salt}{number}".encode("ascii")).hexdigest()
    return {"algorithm": "SHA-256", "salt": salt, "challenge": challenge,
            "maxnumber": _difficulty(), "signature": _sign(key, challenge)}


def check_solution(key: bytes, solution: Any) -> Tuple[bool, str]:
    """(True, "") for a valid, unexpired, unused solution; otherwise (False, why)."""
    if not isinstance(solution, dict):
        return False, "Complete the check first."
    salt, challenge = str(solution.get("salt") or ""), str(solution.get("challenge") or "")
    signature, number = str(solution.get("signature") or ""), solution.get("number")
    try:
        expires = int(salt.split("?expires=", 1)[1])
        number = int(number)
    except (IndexError, TypeError, ValueError):
        return False, "Complete the check first."
    if expires < time.time():
        return False, "The check expired. Try again."
    if not hmac.compare_digest(signature, _sign(key, challenge)):
        return False, "The check failed. Try again."
    if not hmac.compare_digest(hashlib.sha256(f"{salt}{number}".encode("ascii")).hexdigest(), challenge):
        return False, "The check failed. Try again."
    now = time.time()
    with _spent_lock:
        for c in [c for c, t in _spent.items() if t < now]:
            del _spent[c]
        if challenge in _spent:
            return False, "The check was already used. Try again."
        _spent[challenge] = expires
    return True, ""
