"""
Web search agent: answers with cited web pages, like the documents.

When the question needs the web (recent or general information, "search the web", or the
web toggle in the interface), or the documents have nothing relevant, this agent:

1. searches with the first configured provider (Tavily, Brave, Serper, a SearXNG instance,
   or DuckDuckGo without a key), using the English search query of the understanding step;
2. reads the top pages itself (safely: public addresses only, size and time limits) and
   keeps their main text;
3. picks the passages of each page that best answer the question with the reranker.

Each page becomes a numbered "web" source with its URL and passages; the answer cites it as
[n], and the interface opens the page in its own reader with the cited passage highlighted.
No model call is made here.
"""
import os
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, unquote, parse_qs

from core.state import AgentWorkflowState
from agents.llm_utils import trace
from parsing.web import read_page, passages, FetchError, USER_AGENT

logger = logging.getLogger("OmniDoc.WebSearch")

MAX_RESULTS = 6
PAGES_TO_READ = 3
PASSAGES_PER_PAGE = 2
MIN_PASSAGE_SCORE = 0.05
# Below this best document relevance (0-1), the documents are taken not to answer the question.
FALLBACK_SCORE = float(os.getenv("OMNIDOC_WEB_FALLBACK_SCORE", "0.08"))
MODE = os.getenv("OMNIDOC_WEB_SEARCH", "auto").strip().lower()  # auto | on | off

_WEB_CUES = re.compile(r"\b(latest|current(ly)?|today|right now|this (week|month|year)|recent(ly)?|news|breaking|"
                       r"search (the )?(web|internet|online)|look (it )?up online|google|on the internet|online|"
                       r"price of|stock price|weather|exchange rate|who won|released|launch(ed)?|update[sd]?)\b", re.I)


def wants_web(query: str) -> bool:
    return bool(_WEB_CUES.search(query or "")) or bool(re.search(r"\b(20(2[5-9]|3\d))\b", query or ""))


# ------------------------------------------------------------------------- providers
def _tavily(query: str, k: int) -> List[Dict[str, Any]]:
    import httpx
    resp = httpx.post("https://api.tavily.com/search", timeout=20, json={
        "api_key": os.environ["TAVILY_API_KEY"], "query": query, "max_results": k, "search_depth": "basic",
        "include_answer": False})
    resp.raise_for_status()
    return [{"title": r.get("title") or r.get("url"), "url": r.get("url"), "snippet": r.get("content") or "",
             "published": r.get("published_date") or ""} for r in resp.json().get("results") or []]


def _brave(query: str, k: int) -> List[Dict[str, Any]]:
    import httpx
    resp = httpx.get("https://api.search.brave.com/res/v1/web/search", timeout=20, params={"q": query, "count": k},
                     headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"], "Accept": "application/json"})
    resp.raise_for_status()
    return [{"title": r.get("title"), "url": r.get("url"), "snippet": re.sub(r"<[^>]+>", "", r.get("description") or ""),
             "published": r.get("age") or ""} for r in (resp.json().get("web") or {}).get("results") or []]


def _serper(query: str, k: int) -> List[Dict[str, Any]]:
    import httpx
    resp = httpx.post("https://google.serper.dev/search", timeout=20, json={"q": query, "num": k},
                      headers={"X-API-KEY": os.environ["SERPER_API_KEY"]})
    resp.raise_for_status()
    return [{"title": r.get("title"), "url": r.get("link"), "snippet": r.get("snippet") or "", "published": r.get("date") or ""}
            for r in resp.json().get("organic") or []]


def _searxng(query: str, k: int) -> List[Dict[str, Any]]:
    import httpx
    resp = httpx.get(os.environ["SEARXNG_URL"].rstrip("/") + "/search", timeout=20,
                     params={"q": query, "format": "json"})
    resp.raise_for_status()
    return [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content") or "", "published": r.get("publishedDate") or ""}
            for r in (resp.json().get("results") or [])[:k]]


def _duckduckgo(query: str, k: int) -> List[Dict[str, Any]]:
    """DuckDuckGo's HTML results page (no key; unofficial, may be rate-limited)."""
    import httpx
    from bs4 import BeautifulSoup
    resp = httpx.post("https://html.duckduckgo.com/html/", data={"q": query}, timeout=20,
                      headers={"User-Agent": USER_AGENT, "Referer": "https://html.duckduckgo.com/"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    out = []
    for res in soup.select(".result"):
        link = res.select_one("a.result__a")
        if not link or not link.get("href"):
            continue
        href = link["href"]
        if "uddg=" in href:  # redirect wrapper
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        if "duckduckgo.com/y.js" in href or not href.startswith("http"):
            continue  # ads
        snippet = res.select_one(".result__snippet")
        out.append({"title": link.get_text(" ", strip=True), "url": href,
                    "snippet": snippet.get_text(" ", strip=True) if snippet else "", "published": ""})
        if len(out) >= k:
            break
    return out


PROVIDERS = [
    ("tavily", "Tavily", "TAVILY_API_KEY", _tavily),
    ("brave", "Brave Search", "BRAVE_API_KEY", _brave),
    ("serper", "Serper (Google)", "SERPER_API_KEY", _serper),
    ("searxng", "SearXNG", "SEARXNG_URL", _searxng),
    ("duckduckgo", "DuckDuckGo", "", _duckduckgo),
]


def search_providers() -> List[Dict[str, Any]]:
    order = [p.strip() for p in os.getenv("OMNIDOC_SEARCH_PROVIDERS", "").split(",") if p.strip()]
    rows = [{"name": n, "label": label, "configured": not env or bool(os.getenv(env)), "key_env": env, "fn": fn}
            for n, label, env, fn in PROVIDERS]
    if order:
        rows = sorted([r for r in rows if r["name"] in order], key=lambda r: order.index(r["name"]))
    if os.getenv("OMNIDOC_DUCKDUCKGO", "1") == "0":
        rows = [r for r in rows if r["name"] != "duckduckgo"]
    return rows


def web_search(query: str, k: int = MAX_RESULTS) -> Dict[str, Any]:
    """{"provider", "results"} from the first provider that answers."""
    errors = []
    for p in search_providers():
        if not p["configured"]:
            continue
        try:
            results = [r for r in p["fn"](query, k) if r.get("url", "").startswith("http")]
            if results:
                return {"provider": p["label"], "results": results[:k]}
        except Exception as e:
            errors.append(f"{p['label']}: {e}")
            logger.warning(f"Web search with {p['label']} failed: {e}")
    return {"provider": None, "results": [], "errors": errors}


def site_name(url: str) -> str:
    host = urlparse(url).hostname or url
    return host[4:] if host.startswith("www.") else host


class WebSearchAgent:
    """Searches the web, reads the best pages and selects the passages that answer the question."""

    def __init__(self, reranker: Any = None, cache_dir: Optional[str] = None):
        self.reranker = reranker
        self.cache_dir = cache_dir

    def should_search(self, state: AgentWorkflowState) -> str:
        """Why the web is searched for this question ("" when it is not)."""
        mode = (state.get("needs") or {}).get("web_mode") or MODE
        if mode == "off":
            return ""
        if mode == "on":
            return "web search is on"
        if (state.get("needs") or {}).get("web") or wants_web(state.get("user_query", "")):
            return "the question needs current or general information"
        chunks = [c for c in state.get("chunk_context") or [] if isinstance(c, dict) and c.get("chunk_id")]
        best = max([float(c.get("score") or 0) for c in chunks] or [0.0])
        if not (state.get("table_results") or state.get("summary_context")) and best < FALLBACK_SCORE:
            return "the documents do not answer it" if chunks else "there are no matching documents"
        return ""

    def _read(self, result: Dict[str, Any], question: str) -> Optional[Dict[str, Any]]:
        try:
            page = read_page(result["url"], self.cache_dir)
        except (FetchError, Exception) as e:
            logger.info(f"Could not read {result['url']}: {e}")
            page = {"paragraphs": [], "title": result.get("title"), "final_url": result["url"]}
        candidates = passages(page.get("paragraphs") or [])
        if result.get("snippet"):
            candidates.append(result["snippet"])
        if not candidates:
            return None
        scores = self.reranker.score_pairs(question, candidates) if self.reranker else [1.0] * len(candidates)
        ranked = sorted(zip(scores, candidates), key=lambda x: -x[0])
        best = [p for _, p in ranked[:PASSAGES_PER_PAGE]]
        url = page.get("final_url") or result["url"]
        title = page.get("title") if page.get("title") and not str(page.get("title")).startswith("http") else None
        return {
            "title": (title or result.get("title") or url)[:200],
            "url": url,
            "site": site_name(url),
            "published": page.get("published") or result.get("published") or "",
            "snippet": best[0][:600],
            "content": "\n\n".join(best),
            "passages": best,
            "score": round(float(ranked[0][0]), 4),
        }

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        started = time.perf_counter()
        why = self.should_search(state)
        if not why:
            return {}
        semantic_q = state.get("semantic_query")
        variants = (getattr(semantic_q, "constraints", None) or {}).get("retrieval_variants") or []
        question = getattr(semantic_q, "resolved_query", None) or state.get("user_query", "")
        # Search in English when the understanding step wrote English queries (questions in other languages).
        query = (variants[0] if variants and (getattr(semantic_q, "language", "en") or "en") != "en" else question)[:300]
        found = web_search(query)
        results = found["results"]
        if not results:
            detail = "No web results" + (f" ({'; '.join(found.get('errors') or [])[:160]})" if found.get("errors") else "")
            return {"agent_traces": [trace("web_search", "failed", detail, started)]}
        with ThreadPoolExecutor(max_workers=PAGES_TO_READ) as pool:
            pages = list(pool.map(lambda r: self._read(r, question), results[:PAGES_TO_READ + 1]))
        pages = sorted([p for p in pages if p], key=lambda p: -p["score"])
        # Keep pages whose best passage is relevant (at least the best page, whatever its score).
        kept = [p for p in pages if p["score"] >= MIN_PASSAGE_SCORE][:PAGES_TO_READ] or pages[:1]
        detail = f"{found['provider']}: {len(results)} results, read {len(kept)} page(s) because {why}"
        return {"web_context": kept, "agent_traces": [trace("web_search", "completed", detail, started)]}
