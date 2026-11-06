"""
A web front end on another host (Vercel) that forwards /api to this server.

The browser opens the front end's address, which serves the web app and rewrites /api/* to this
server, so the site stays on one origin: cookies, passkeys and sign-in need nothing cross-site.
The rewrite's destination carries a secret path prefix, /_via/<OMNIDOC_PROXY_KEY>/api/..., that no
visitor sees. A request with the prefix came through the front end, so:

* the prefix is removed before routing;
* the visitor's address is taken from the front end's header (x-vercel-forwarded-for, x-real-ip or
  the first X-Forwarded-For entry, all set by Vercel and not by the visitor), so per-address limits
  apply per visitor and not to the front end's handful of addresses;
* responses without a Cache-Control header are marked private, so the front end's CDN never keeps
  one visitor's answer for another.

A request without the prefix is handled as before (Caddy's X-Forwarded-For, see abuse.client_ip),
and those headers are not believed.
"""
import hmac
import ipaddress
import os
from typing import Any, Callable, Dict, Optional

PREFIX = "/_via/"
_VISITOR_HEADERS = (b"x-vercel-forwarded-for", b"x-real-ip", b"x-forwarded-for")


def _key() -> str:
    return os.getenv("OMNIDOC_PROXY_KEY", "").strip()


def _visitor_ip(headers: Dict[bytes, bytes]) -> Optional[str]:
    for name in _VISITOR_HEADERS:
        value = headers.get(name)
        if not value:
            continue
        first = value.decode("latin-1").split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(first))
        except ValueError:
            continue
    return None


def split(path: str, key: str) -> Optional[str]:
    """The path after /_via/<key> when it carries the right key, else None."""
    if not key or not path.startswith(PREFIX):
        return None
    given, _, rest = path[len(PREFIX):].partition("/")
    if not hmac.compare_digest(given.encode(), key.encode()):
        return None
    return "/" + rest


class FrontProxy:
    """ASGI middleware: recognises requests forwarded by the front end (see the module docstring)."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        key = _key()
        path = split(scope.get("path", ""), key)
        if path is None:
            if scope["type"] == "http" and scope.get("path", "").startswith(PREFIX):
                # A guessed or stale prefix: not found, rather than the web app's page.
                await send({"type": "http.response.start", "status": 404, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Not found"})
                return
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        visitor = _visitor_ip(headers)
        raw = scope.get("raw_path")
        cut = len(PREFIX) + len(key)
        scope = dict(scope, path=path, raw_path=raw[cut:] if isinstance(raw, bytes) and len(raw) > cut else path.encode())
        if visitor:
            scope["client"] = (visitor, 0)

        async def private_send(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                if b"cache-control" not in names:
                    message = dict(message, headers=[*message.get("headers", []), (b"cache-control", b"private, no-cache")])
            await send(message)

        await self.app(scope, receive, private_send)
