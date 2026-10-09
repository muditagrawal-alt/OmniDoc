"""
Language-model providers for OmniDoc.

Every model call goes through ``agents.llm_utils.chat`` with a model *spec*:

    "qwen2.5:7b-instruct"              a local Ollama model (also "ollama:qwen2.5:7b-instruct")
    "groq:openai/gpt-oss-120b"         a hosted model behind an OpenAI-compatible API

Hosted providers are switched on by an API key in the environment or in ``.env``. When a
provider is rate-limited, failing, out of quota or too small for a request, the call moves
to the next configured provider (and finally to local Ollama when it is running), so the
free tiers of several providers can be chained. Each provider has a "smart" model (writing,
SQL, checking) and a "fast" model (understanding a question, background summaries).

Usage per question (calls, tokens, providers) is recorded under the run id set by the
workflow, so the execution budget and the answer footer can report it.
"""
import os
import re
import json
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("OmniDoc.Providers")

try:  # API keys may live in a .env file next to server.py
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=False)
except Exception:  # python-dotenv is optional
    pass

LLM_TIMEOUT_S = float(os.getenv("OMNIDOC_LLM_TIMEOUT", "300"))
# Quick calls (understanding, judging, extraction batches) give up sooner so a stalled provider
# falls through to the next one instead of holding up the answer.
FAST_TIMEOUT_S = float(os.getenv("OMNIDOC_FAST_TIMEOUT", "60"))


@dataclass
class Provider:
    name: str
    label: str
    base_url: str
    key_env: str
    model: str
    fast_model: str
    vision_model: str = ""
    embed_model: str = ""
    rpm: int = 30            # requests per minute allowed on the free tier (client-side pacing)
    tpm: int = 0             # tokens per minute; 0 = no known limit
    reasoning: str = ""      # "gpt-oss" | "gemini" | "nemotron" | "" : how to turn model thinking down
    free_note: str = ""
    sign_up: str = ""
    extra_headers: Dict[str, str] = field(default_factory=dict)
    key_aliases: Tuple[str, ...] = ()  # other names people give the key in .env

    @property
    def api_key(self) -> str:
        for env in (self.key_env,) + self.key_aliases:
            value = (os.getenv(env) or "").strip()
            if value:
                return value
        return ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url)


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _provider(name: str, label: str, base_url: str, key_env: str, model: str, fast: str, **kw: Any) -> Provider:
    up = name.upper()
    return Provider(
        name=name, label=label,
        base_url=_env(f"{up}_BASE_URL", base_url).rstrip("/"),
        key_env=key_env,
        model=_env(f"{up}_MODEL", model),
        fast_model=_env(f"{up}_FAST_MODEL", fast),
        vision_model=_env(f"{up}_VISION_MODEL", kw.pop("vision_model", "")),
        embed_model=_env(f"{up}_EMBED_MODEL", kw.pop("embed_model", "")),
        **kw,
    )


def build_registry() -> Dict[str, Provider]:
    """Known OpenAI-compatible providers. Defaults are free-tier models; override with <NAME>_MODEL etc."""
    providers = [
        _provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY",
                  "gemini-3.5-flash", "gemini-3.5-flash-lite", vision_model="gemini-3.5-flash",
                  embed_model="gemini-embedding-001", rpm=10, tpm=250_000, reasoning="gemini",
                  free_note="Free tier in Google AI Studio; prompts may be used to improve Google's models outside the EEA, UK and Switzerland.",
                  sign_up="https://aistudio.google.com/apikey"),
        _provider("groq", "Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
                  "openai/gpt-oss-120b", "openai/gpt-oss-20b", rpm=30, tpm=8_000, reasoning="gpt-oss",
                  free_note="Free plan: 30 requests/min, 1,000/day and 8,000 tokens/min per model; Whisper speech-to-text included.",
                  sign_up="https://console.groq.com/keys"),
        _provider("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY",
                  "nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3-super-120b-a12b", rpm=40,
                  reasoning="nemotron", key_aliases=("NVIDIA_NIM_API_KEY", "NIM_API_KEY"),
                  free_note="Free with an NVIDIA Developer account (about 40 requests/min per model); meant for development and evaluation.",
                  sign_up="https://build.nvidia.com"),
        _provider("mistral", "Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY",
                  "mistral-medium-latest", "mistral-small-latest", vision_model="mistral-small-latest",
                  embed_model="mistral-embed", rpm=60,
                  free_note="Free Experiment plan; requests may be used for training unless you opt out.",
                  sign_up="https://console.mistral.ai/api-keys"),
        _provider("cerebras", "Cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY",
                  "gpt-oss-120b", "llama3.1-8b", rpm=30, tpm=60_000, reasoning="gpt-oss",
                  free_note="Very fast; new accounts now start with a trial credit.",
                  sign_up="https://cloud.cerebras.ai"),
        _provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
                  "nvidia/nemotron-3-super-120b-a12b:free", "google/gemma-4-31b-it:free", rpm=20,
                  free_note="Models ending in :free cost nothing; 50 requests/day (1,000 after a one-time $10 top-up).",
                  sign_up="https://openrouter.ai/keys",
                  extra_headers={"HTTP-Referer": "https://github.com/omnidoc", "X-Title": "OmniDoc"}),
        _provider("github", "GitHub Models", "https://models.github.ai/inference", "GITHUB_MODELS_TOKEN",
                  "openai/gpt-4.1-mini", "openai/gpt-4.1-nano", rpm=15,
                  free_note="Free for prototyping with a GitHub token (models:read); low daily limits.",
                  sign_up="https://github.com/settings/tokens"),
        _provider("jina", "Jina AI (embeddings)", "https://api.jina.ai/v1", "JINA_API_KEY", "", "",
                  embed_model="jina-embeddings-v3", rpm=100,
                  free_note="Free starter tokens for embeddings and reranking.", sign_up="https://jina.ai/embeddings"),
        _provider("custom", "Custom (OpenAI-compatible)", os.getenv("OMNIDOC_LLM_BASE_URL", ""), "OMNIDOC_LLM_API_KEY",
                  os.getenv("OMNIDOC_LLM_MODEL", ""), os.getenv("OMNIDOC_LLM_FAST_MODEL", os.getenv("OMNIDOC_LLM_MODEL", "")),
                  free_note="Any OpenAI-compatible endpoint (LM Studio, vLLM, Together, ...)."),
    ]
    return {p.name: p for p in providers}


REGISTRY: Dict[str, Provider] = build_registry()
DEFAULT_ORDER = ["gemini", "groq", "nvidia", "mistral", "cerebras", "openrouter", "github", "custom"]


def chat_providers() -> List[Provider]:
    """Configured providers that serve chat models, in fallback order (OMNIDOC_LLM_PROVIDERS overrides)."""
    order = [p.strip().lower() for p in os.getenv("OMNIDOC_LLM_PROVIDERS", "").split(",") if p.strip()] or DEFAULT_ORDER
    return [REGISTRY[n] for n in order if n in REGISTRY and REGISTRY[n].configured and REGISTRY[n].model]


def parse_spec(spec: str) -> Tuple[str, str]:
    """'groq:openai/gpt-oss-120b' -> ('groq', 'openai/gpt-oss-120b'); anything else is an Ollama model."""
    spec = (spec or "").strip()
    if ":" in spec:
        prefix, rest = spec.split(":", 1)
        if prefix.lower() in REGISTRY:
            return prefix.lower(), rest
        if prefix.lower() == "ollama":
            return "ollama", rest
    return "ollama", spec


def spec_for(provider: str, model: str) -> str:
    return model if provider == "ollama" else f"{provider}:{model}"


# ---------------------------------------------------------------------------------- usage
_run = threading.local()
_stats_lock = threading.Lock()
RUN_STATS: Dict[str, Dict[str, Any]] = {}


def set_current_run(run_id: Optional[str]) -> None:
    _run.id = run_id


def current_run() -> Optional[str]:
    return getattr(_run, "id", None)


def _record(provider: str, model: str, prompt_tokens: int, completion_tokens: int, seconds: float) -> None:
    run_id = current_run()
    if not run_id:
        return
    with _stats_lock:
        s = RUN_STATS.setdefault(run_id, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0, "models": {}})
        s["calls"] += 1
        s["prompt_tokens"] += int(prompt_tokens or 0)
        s["completion_tokens"] += int(completion_tokens or 0)
        s["seconds"] = round(s["seconds"] + seconds, 2)
        key = spec_for(provider, model)
        s["models"][key] = s["models"].get(key, 0) + 1


def run_stats(run_id: str, pop: bool = False) -> Dict[str, Any]:
    with _stats_lock:
        s = RUN_STATS.pop(run_id, None) if pop else RUN_STATS.get(run_id)
        return dict(s) if s else {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0, "models": {}}


# ------------------------------------------------------------------------- availability
_cooldown: Dict[str, float] = {}
_recent: Dict[str, List[float]] = {}
_pace_lock = threading.Lock()
_no_extras: Dict[str, bool] = {}   # providers that rejected optional request fields


class ProviderError(Exception):
    """A provider could not serve the request; ``retryable`` means another provider may."""

    def __init__(self, message: str, retryable: bool = True, status: int = 0):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


def _available(p: Provider, est_tokens: int) -> Tuple[bool, str]:
    now = time.time()
    if _cooldown.get(p.name, 0) > now:
        return False, f"cooling down for {int(_cooldown[p.name] - now)}s"
    if p.tpm and est_tokens > 0.9 * p.tpm:
        return False, f"request (~{est_tokens} tokens) exceeds its {p.tpm} tokens/min limit"
    with _pace_lock:
        window = [t for t in _recent.get(p.name, []) if now - t < 60]
        _recent[p.name] = window
        if len(window) >= p.rpm:
            return False, f"{p.rpm} requests/min reached"
    return True, ""


def _mark_used(p: Provider) -> None:
    with _pace_lock:
        _recent.setdefault(p.name, []).append(time.time())


def _cool(p: Provider, seconds: float, reason: str) -> None:
    _cooldown[p.name] = time.time() + seconds
    logger.warning(f"{p.label}: {reason}; skipping it for {int(seconds)}s.")


def provider_status() -> List[Dict[str, Any]]:
    now = time.time()
    out = []
    for name in DEFAULT_ORDER + ["jina"]:
        p = REGISTRY[name]
        out.append({
            "name": p.name, "label": p.label, "configured": p.configured, "model": p.model, "fast_model": p.fast_model,
            "vision_model": p.vision_model, "embed_model": p.embed_model, "key_env": p.key_env,
            "cooling_down_s": max(0, int(_cooldown.get(p.name, 0) - now)), "free_note": p.free_note, "sign_up": p.sign_up,
        })
    return out


# ------------------------------------------------------------------------------- HTTP
_client = None
_client_lock = threading.Lock()
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _http():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import httpx
                _client = httpx.Client(timeout=httpx.Timeout(LLM_TIMEOUT_S, connect=15.0))
    return _client


def strip_thinking(text: str) -> str:
    text = _THINK_RE.sub("", text or "")
    if "<think>" in text and "</think>" not in text:  # thinking cut off by the token limit
        text = text.split("<think>", 1)[0]
    return text.strip()


def _headers(p: Provider) -> Dict[str, str]:
    h = {"Authorization": f"Bearer {p.api_key}", "Content-Type": "application/json"}
    h.update(p.extra_headers)
    return h


def _body(p: Provider, model: str, messages: List[Dict[str, Any]], *, temperature: float, max_tokens: int,
          json_mode: bool, schema: Optional[Dict[str, Any]], fast: bool, stream: bool, extras: bool) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature, "stream": stream}
    reasoning_model = p.reasoning == "gpt-oss" or "gpt-oss" in model
    thinks = reasoning_model or (p.reasoning == "nemotron" and not (fast or json_mode))
    # Reasoning tokens count against the limit: leave room so the answer is not cut off.
    body["max_tokens"] = max_tokens + (1024 if thinks else 0)
    if not extras or _no_extras.get(p.name):
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body
    if json_mode and schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": schema}}
    elif json_mode:
        body["response_format"] = {"type": "json_object"}
    if reasoning_model:
        body["reasoning_effort"] = "low" if (fast or json_mode) else "medium"
    elif p.reasoning == "gemini":
        body["reasoning_effort"] = "none" if fast or json_mode else "low"
    elif p.reasoning == "nemotron":
        body["chat_template_kwargs"] = {"enable_thinking": False} if fast or json_mode else \
            {"enable_thinking": True, "low_effort": True}
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def _raise_for(p: Provider, resp: Any) -> None:
    status = resp.status_code
    text = ""
    try:
        text = resp.text[:400]
    except Exception:
        pass
    if status == 429:
        retry = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset-requests") or ""
        try:
            wait = float(re.findall(r"[\d.]+", retry)[0])
        except Exception:
            wait = 30.0
        daily = bool(re.search(r"per ?day|daily|PerDay|RPD|TPD|quota", text, re.I))
        _cool(p, max(wait, 3600.0 if daily else 20.0), "rate limit" + (" (daily quota)" if daily else ""))
        raise ProviderError(f"{p.label} rate limit", retryable=True, status=status)
    if status in (401, 403):
        _cool(p, 600, f"rejected the API key ({status})")
        raise ProviderError(f"{p.label} rejected the API key", retryable=True, status=status)
    if status >= 500 or status in (408, 409, 425):
        _cool(p, 30, f"server error {status}")
        raise ProviderError(f"{p.label} server error {status}", retryable=True, status=status)
    raise ProviderError(f"{p.label} error {status}: {text}", retryable=False, status=status)


def openai_chat(p: Provider, model: str, messages: List[Dict[str, Any]], *, temperature: float = 0.0,
                max_tokens: int = 512, json_mode: bool = False, schema: Optional[Dict[str, Any]] = None,
                fast: bool = False) -> str:
    """One chat completion from an OpenAI-compatible provider (retries once without optional fields on 400)."""
    import httpx
    url = f"{p.base_url}/chat/completions"
    for extras in (True, False):
        body = _body(p, model, messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode,
                     schema=schema, fast=fast, stream=False, extras=extras)
        started = time.perf_counter()
        _mark_used(p)
        try:
            resp = _http().post(url, headers=_headers(p), json=body,
                                timeout=FAST_TIMEOUT_S if fast else LLM_TIMEOUT_S)
        except httpx.HTTPError as e:
            _cool(p, 30, f"unreachable ({type(e).__name__})")
            raise ProviderError(f"{p.label} unreachable: {e}", retryable=True)
        if resp.status_code == 400 and extras:
            logger.info(f"{p.label} rejected optional request fields; retrying plainly. {resp.text[:200]}")
            _no_extras[p.name] = True
            continue
        if resp.status_code >= 400:
            _raise_for(p, resp)
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        _record(p.name, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), time.perf_counter() - started)
        return strip_thinking(content if isinstance(content, str) else json.dumps(content))
    raise ProviderError(f"{p.label} rejected the request", retryable=True)


def openai_stream(p: Provider, model: str, messages: List[Dict[str, Any]], on_delta: Callable[[str], None], *,
                  temperature: float = 0.2, max_tokens: int = 1500, fast: bool = False) -> str:
    """Streams a chat completion, calling on_delta with each piece of visible text. Returns the full text."""
    import httpx
    url = f"{p.base_url}/chat/completions"
    for extras in (True, False):
        body = _body(p, model, messages, temperature=temperature, max_tokens=max_tokens, json_mode=False,
                     schema=None, fast=fast, stream=True, extras=extras)
        started = time.perf_counter()
        _mark_used(p)
        parts: List[str] = []
        usage: Dict[str, Any] = {}
        think = ThinkFilter()
        try:
            with _http().stream("POST", url, headers=_headers(p), json=body) as resp:
                if resp.status_code == 400 and extras:
                    resp.read()
                    _no_extras[p.name] = True
                    continue
                if resp.status_code >= 400:
                    resp.read()
                    _raise_for(p, resp)
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except ValueError:
                        continue
                    if data.get("usage"):
                        usage = data["usage"]
                    for choice in data.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            visible = think.feed(piece)
                            if visible:
                                parts.append(visible)
                                on_delta(visible)
                tail = think.flush()
                if tail:
                    parts.append(tail)
                    on_delta(tail)
        except httpx.HTTPError as e:
            if parts:
                raise ProviderError(f"{p.label} stream interrupted: {e}", retryable=False)
            _cool(p, 30, f"unreachable ({type(e).__name__})")
            raise ProviderError(f"{p.label} unreachable: {e}", retryable=True)
        _record(p.name, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), time.perf_counter() - started)
        return strip_thinking("".join(parts))
    raise ProviderError(f"{p.label} rejected the request", retryable=True)


def openai_embed(p: Provider, model: str, texts: List[str]) -> List[List[float]]:
    import httpx
    body: Dict[str, Any] = {"model": model, "input": texts}
    if p.name == "jina":
        body["task"] = "retrieval.passage"
    try:
        resp = _http().post(f"{p.base_url}/embeddings", headers=_headers(p), json=body)
    except httpx.HTTPError as e:
        raise ProviderError(f"{p.label} unreachable: {e}", retryable=True)
    if resp.status_code >= 400:
        _raise_for(p, resp)
    data = sorted(resp.json().get("data") or [], key=lambda d: d.get("index", 0))
    return [list(map(float, d["embedding"])) for d in data]


def openai_transcribe(p: Provider, model: str, file_path: str) -> Dict[str, Any]:
    """Speech to text (Whisper) with segment timestamps."""
    import httpx
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        data = {"model": model, "response_format": "verbose_json", "timestamp_granularities[]": "segment"}
        try:
            resp = _http().post(f"{p.base_url}/audio/transcriptions", headers={"Authorization": f"Bearer {p.api_key}"},
                                data=data, files=files, timeout=600)
        except httpx.HTTPError as e:
            raise ProviderError(f"{p.label} unreachable: {e}", retryable=True)
    if resp.status_code >= 400:
        _raise_for(p, resp)
    return resp.json()


def _partial_suffix(text: str, tag: str) -> int:
    """Length of the longest end of ``text`` that could be the start of ``tag``."""
    for k in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:k]):
            return k
    return 0


class ThinkFilter:
    """Hides <think>...</think> blocks from streamed text (tags may be split across pieces)."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.inside = False
        self.buffer = ""

    def feed(self, piece: str) -> str:
        self.buffer += piece
        out: List[str] = []
        while self.buffer:
            if self.inside:
                end = self.buffer.find(self.CLOSE)
                if end < 0:
                    self.buffer = self.buffer[-(len(self.CLOSE) - 1):]
                    break
                self.buffer = self.buffer[end + len(self.CLOSE):].lstrip()
                self.inside = False
                continue
            start = self.buffer.find(self.OPEN)
            if start < 0:
                keep = _partial_suffix(self.buffer, self.OPEN)
                out.append(self.buffer[:len(self.buffer) - keep])
                self.buffer = self.buffer[len(self.buffer) - keep:]
                break
            out.append(self.buffer[:start])
            self.buffer = self.buffer[start + len(self.OPEN):]
            self.inside = True
        return "".join(out)

    def flush(self) -> str:
        rest, self.buffer = ("" if self.inside else self.buffer), ""
        return rest


def estimate_tokens(messages: List[Dict[str, Any]], max_tokens: int) -> int:
    chars = 0
    for m in messages:
        c = m.get("content")
        chars += len(c) if isinstance(c, str) else len(json.dumps(c)) // 4
    return chars // 4 + max_tokens


def candidates(spec: str, *, allow_fallback: bool = True) -> Iterator[Tuple[str, Optional[Provider], str]]:
    """
    The (kind, provider, model) sequence to try for a spec: the requested provider first, then
    the other configured hosted providers, then local Ollama (when the request was for a
    hosted model and OMNIDOC_LOCAL_FALLBACK is not 0). A request for a local model stays local
    unless OMNIDOC_CLOUD_FALLBACK=1.
    """
    kind, model = parse_spec(spec)
    if kind == "ollama":
        yield "ollama", None, model
        if allow_fallback and os.getenv("OMNIDOC_CLOUD_FALLBACK", "0") == "1":
            for p in chat_providers():
                yield p.name, p, p.model
        return
    primary = REGISTRY.get(kind)
    if primary is not None and primary.configured:
        yield primary.name, primary, model or primary.model
    if not allow_fallback:
        return
    for p in chat_providers():
        if primary is None or p.name != primary.name:
            yield p.name, p, p.model
    if os.getenv("OMNIDOC_LOCAL_FALLBACK", "1") != "0":
        yield "ollama", None, os.getenv("OMNIDOC_OLLAMA_MODEL", "qwen2.5:7b-instruct")


def fast_variant(p: Optional[Provider], model: str) -> str:
    """The provider's fast model when ``model`` is its default smart model."""
    if p is None:
        return os.getenv("OMNIDOC_OLLAMA_FAST_MODEL", model)
    return p.fast_model if (model == p.model and p.fast_model) else model


def default_spec() -> str:
    """The model used when none was chosen: the first configured hosted provider, else local Ollama."""
    explicit = os.getenv("OMNIDOC_MODEL", "").strip()
    if explicit:
        return explicit
    hosted = chat_providers()
    if hosted:
        return spec_for(hosted[0].name, hosted[0].model)
    return "qwen2.5:7b-instruct"


def is_available(p: Provider, est_tokens: int) -> Tuple[bool, str]:
    return _available(p, est_tokens)
