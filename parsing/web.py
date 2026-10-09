"""
Fetching web pages safely and reading their main text.

``safe_get`` refuses anything but http(s) to public addresses (no localhost, private,
link-local or reserved networks, checked after DNS resolution and again after redirects),
limits size and time, and returns the body with its content type. ``readable`` keeps the
article of an HTML page (title, site, publication date and paragraphs) and drops
navigation, scripts, footers and other boilerplate. Pages are cached on disk for a day.
"""
import os
import re
import json
import time
import socket
import hashlib
import logging
import ipaddress
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("OmniDoc.Web")

MAX_BYTES = int(os.getenv("OMNIDOC_WEB_MAX_BYTES", str(4 * 1024 * 1024)))
TIMEOUT_S = float(os.getenv("OMNIDOC_WEB_TIMEOUT", "10"))
CACHE_TTL_S = 24 * 3600
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 OmniDoc/2"
_DROP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe", "button",
              "figure", "template", "dialog", "select", "input")
_BOILER = re.compile(r"(nav|menu|footer|header|sidebar|cookie|banner|subscribe|newsletter|share|social|comment|related|"
                     r"advert|promo|popup|modal|breadcrumb|signup|login)", re.I)


class FetchError(Exception):
    pass


def _public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global)):
            return False
    return True


def check_url(url: str) -> str:
    """Returns the URL if it is an http(s) URL of a public host; raises FetchError otherwise."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("Only http and https addresses can be opened.")
    if parsed.username or parsed.password:
        raise FetchError("Addresses with credentials are not allowed.")
    if not _public(parsed.hostname):
        raise FetchError("That address points to a private or local network.")
    return parsed.geturl()


def safe_get(url: str, max_bytes: int = MAX_BYTES, accept: str = "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.5") -> Tuple[bytes, str, str]:
    """(body, content type, final URL). Follows up to 5 redirects, re-checking each address."""
    import httpx
    current = check_url(url)
    with httpx.Client(timeout=httpx.Timeout(TIMEOUT_S, connect=6.0), follow_redirects=False,
                      headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "en,*;q=0.5"}) as client:
        for _ in range(6):
            with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    current = check_url(urljoin(current, resp.headers["location"]))
                    continue
                if resp.status_code >= 400:
                    raise FetchError(f"The site answered {resp.status_code}.")
                declared = int(resp.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise FetchError("The page is too large.")
                body = b""
                for piece in resp.iter_bytes():
                    body += piece
                    if len(body) > max_bytes:
                        raise FetchError("The page is too large.")
                return body, resp.headers.get("content-type", "").split(";")[0].strip().lower(), str(resp.url)
    raise FetchError("Too many redirects.")


def _text(node: Any) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def readable(html: str, url: str = "") -> Dict[str, Any]:
    """{"title", "site", "published", "paragraphs": [...]} of an HTML page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    meta = {}
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or "").lower()
        if key and tag.get("content"):
            meta[key] = tag["content"].strip()
    title = meta.get("og:title") or (soup.title.get_text(strip=True) if soup.title else "") or url
    site = meta.get("og:site_name") or urlparse(url).hostname or ""
    published = meta.get("article:published_time") or meta.get("date") or meta.get("dc.date") or ""
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all(attrs={"class": _BOILER}):
        if tag.name not in ("html", "body", "main", "article"):
            tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    paragraphs: List[str] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "pre", "td"]):
        if el.find(["p", "li"]) and el.name in ("li", "td", "blockquote"):
            continue  # nested containers: their paragraphs are taken on their own
        text = _text(el)
        if len(text) < 25 and el.name not in ("h1", "h2", "h3", "h4"):
            continue
        if el.name.startswith("h"):
            text = f"## {text}"
        if not paragraphs or paragraphs[-1] != text:
            paragraphs.append(text)
    found = sum(len(p) for p in paragraphs)
    whole = len(root.get_text(" ", strip=True))
    if found < 200 and whole > 3 * max(found, 1):  # pages without paragraph markup
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", root.get_text("\n", strip=True)) if len(p.strip()) > 40]
    return {"title": title[:300], "site": site[:120], "published": published[:40], "paragraphs": paragraphs[:400]}


def _pdf_paragraphs(body: bytes) -> List[str]:
    import fitz
    with fitz.open("pdf", body) as doc:
        text = "\n".join(page.get_text() for page in doc[:40])
    return [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 40][:400]


def read_page(url: str, cache_dir: Optional[str] = None) -> Dict[str, Any]:
    """Fetches and reads a page (cached). Returns {"url", "final_url", "title", "site", "published", "paragraphs"}."""
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    path = os.path.join(cache_dir, f"{key}.json") if cache_dir else None
    if path and os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL_S:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    body, ctype, final_url = safe_get(url)
    if ctype == "application/pdf" or body[:5] == b"%PDF-":
        page = {"title": os.path.basename(urlparse(final_url).path) or final_url, "site": urlparse(final_url).hostname or "",
                "published": "", "paragraphs": _pdf_paragraphs(body)}
    elif ctype.startswith("text/plain"):
        text = body.decode("utf-8", errors="replace")
        page = {"title": final_url, "site": urlparse(final_url).hostname or "", "published": "",
                "paragraphs": [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()][:400]}
    else:
        page = readable(body.decode("utf-8", errors="replace"), final_url)
    page.update(url=url, final_url=final_url)
    if path:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(page, f, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    return page


def passages(paragraphs: List[str], words: int = 140) -> List[str]:
    """Paragraphs grouped into passages of about ``words`` words (headings start a new passage)."""
    out, current, count = [], [], 0
    for p in paragraphs:
        n = len(p.split())
        if current and (p.startswith("## ") or count + n > words):
            out.append(" ".join(current))
            current, count = [], 0
        current.append(p[3:] if p.startswith("## ") else p)
        count += n
    if current:
        out.append(" ".join(current))
    return [p for p in out if len(p.split()) >= 12]
