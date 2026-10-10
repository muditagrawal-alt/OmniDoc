"""
Shared helpers for OmniDoc agents and guardrails:

* one entry point for model calls (``chat``, ``chat_json``, ``chat_stream``, ``vision_chat``)
  that serves local Ollama models and free hosted APIs, falling back from one provider to
  the next on rate limits or errors (see agents/llm_providers.py),
* tolerant JSON parsing / repair for LLM output,
* number extraction used to check that figures really come from the evidence,
* a small helper for ``agent_traces`` entries.
"""
import os
import re
import json
import time
import math
import base64
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import ollama

from agents import llm_providers as providers
from agents.llm_providers import ProviderError, ThinkFilter, strip_thinking

logger = logging.getLogger("OmniDoc.LLM")

DEFAULT_NUM_CTX = int(os.getenv("OMNIDOC_NUM_CTX", "8192"))
LLM_TIMEOUT_S = float(os.getenv("OMNIDOC_LLM_TIMEOUT", "300"))
# Longest wait for a paused provider before a call gives up (see _route).
ROUTE_WAIT_S = float(os.getenv("OMNIDOC_ROUTE_WAIT", "30"))

_client = None
_client_lock = threading.Lock()
_ollama_seen = {"at": 0.0, "up": False}


def get_client() -> "ollama.Client":
    """Lazily creates one shared Ollama client (honours OLLAMA_HOST) with a request timeout."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = ollama.Client(timeout=LLM_TIMEOUT_S)
    return _client


def ollama_reachable(max_age: float = 30.0) -> bool:
    """Whether the local Ollama server answers (cached for ``max_age`` seconds)."""
    now = time.time()
    if now - _ollama_seen["at"] > max_age:
        try:
            import urllib.request
            host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
            if not host.startswith("http"):
                host = "http://" + host
            urllib.request.urlopen(f"{host}/api/tags", timeout=1.0).read(1)
            _ollama_seen["up"] = True
        except Exception:
            _ollama_seen["up"] = False
        _ollama_seen["at"] = now
    return _ollama_seen["up"]


def _ollama_chat(model: str, messages: List[Dict[str, Any]], *, json_mode: bool, schema: Optional[Dict[str, Any]],
                 temperature: float, num_predict: int, num_ctx: Optional[int],
                 on_delta: Optional[Callable[[str], None]] = None) -> str:
    options = {"temperature": temperature, "num_predict": num_predict, "num_ctx": num_ctx or DEFAULT_NUM_CTX}
    kwargs: Dict[str, Any] = {}
    if json_mode:
        kwargs["format"] = schema or "json"
    started = time.perf_counter()
    stream = on_delta is not None
    try:
        # Thinking models (qwen3.5, gemma4) otherwise spend the whole token budget
        # thinking and return empty content; models without thinking ignore the flag.
        resp = get_client().chat(model=model, messages=messages, options=options, stream=stream, think=False, **kwargs)
    except TypeError:  # ollama client older than 0.5
        resp = get_client().chat(model=model, messages=messages, options=options, stream=stream, **kwargs)
    if stream:
        think, parts = ThinkFilter(), []
        prompt_tokens = completion_tokens = 0
        for chunk in resp:
            piece = _field(_field(chunk, "message"), "content") or ""
            visible = think.feed(piece) if piece else ""
            if visible:
                parts.append(visible)
                on_delta(visible)
            if _field(chunk, "done"):
                prompt_tokens = _field(chunk, "prompt_eval_count") or 0
                completion_tokens = _field(chunk, "eval_count") or 0
        tail = think.flush()
        if tail:
            parts.append(tail)
            on_delta(tail)
        providers._record("ollama", model, prompt_tokens, completion_tokens, time.perf_counter() - started)
        return strip_thinking("".join(parts))
    content = _field(_field(resp, "message"), "content") or ""
    providers._record("ollama", model, _field(resp, "prompt_eval_count") or 0, _field(resp, "eval_count") or 0,
                      time.perf_counter() - started)
    return strip_thinking(content)


def _field(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    try:
        return obj[key]
    except Exception:
        return getattr(obj, key, None)


def _route(model: str, messages: List[Dict[str, Any]], call: Callable[[str, Optional[Any], str], str],
           num_predict: int) -> str:
    """
    Tries the providers for ``model`` in order until one answers. ``call(kind, provider,
    model)`` performs the request. When none answered because of a pause that ends soon (a
    rate limit, a server error or timeout, the per-minute window), waits for the first provider
    to free up (at most ROUTE_WAIT_S) and tries again, twice at most: with a single API key
    this is the difference between a slower answer and no answer.
    """
    est = providers.estimate_tokens(messages, num_predict)
    errors: List[str] = []
    for attempt in range(3):
        waitable = False
        for kind, p, m in providers.candidates(model):
            if p is None:
                primary = providers.parse_spec(model)[0] == "ollama"
                if not primary and not ollama_reachable():
                    continue
                tried = True
                try:
                    return call("ollama", None, m)
                except Exception as e:
                    errors.append(f"Ollama ({m}): {e}")
                    continue
            ok, why = providers.is_available(p, est)
            if not ok:
                errors.append(f"{p.label}: {why}")
                waitable = True
                continue
            try:
                return call(kind, p, m)
            except ProviderError as e:
                errors.append(str(e))
                waitable = waitable or e.retryable
                logger.warning(f"{e}; trying the next provider.")
        waits = [w for w in (providers.wait_seconds(p, est) for _, p, _ in providers.candidates(model) if p is not None)
                 if w is not None]
        if attempt == 2 or not waitable or not waits or min(waits) > ROUTE_WAIT_S:
            break
        logger.info(f"Every provider is paused; waiting {min(waits):.0f}s before trying again.")
        time.sleep(max(1.0, min(waits)))
    raise RuntimeError("No language model could answer: " + "; ".join(errors[-6:]))


def chat(
    model: str,
    messages: List[Dict[str, Any]],
    *,
    json_mode: bool = False,
    temperature: float = 0.0,
    num_predict: int = 512,
    num_ctx: Optional[int] = None,
    fast: bool = False,
    schema: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Single non-streaming chat call; returns the stripped message content (raises when no
    provider could answer). ``fast`` uses the provider's fast model; ``schema`` constrains
    JSON output where the provider supports it.
    """
    def call(kind: str, p: Any, m: str) -> str:
        if p is None:
            mm = providers.fast_variant(None, m) if fast else m
            return _ollama_chat(mm, messages, json_mode=json_mode, schema=schema, temperature=temperature,
                                num_predict=num_predict, num_ctx=num_ctx)
        mm = providers.fast_variant(p, m) if fast else m
        return providers.openai_chat(p, mm, messages, temperature=temperature, max_tokens=num_predict,
                                     json_mode=json_mode, schema=schema, fast=fast)
    return _route(model, messages, call, num_predict)


def chat_stream(
    model: str,
    messages: List[Dict[str, Any]],
    on_delta: Callable[[str], None],
    *,
    on_reset: Optional[Callable[[], None]] = None,
    temperature: float = 0.2,
    num_predict: int = 1500,
    num_ctx: Optional[int] = None,
) -> str:
    """Streams the answer through ``on_delta``; if a provider fails midway, ``on_reset`` clears what was shown."""
    def call(kind: str, p: Any, m: str) -> str:
        shown = {"any": False}

        def emit(piece: str) -> None:
            shown["any"] = True
            on_delta(piece)
        try:
            if p is None:
                return _ollama_chat(m, messages, json_mode=False, schema=None, temperature=temperature,
                                    num_predict=num_predict, num_ctx=num_ctx, on_delta=emit)
            return providers.openai_stream(p, m, messages, emit, temperature=temperature, max_tokens=num_predict)
        except Exception as e:
            if shown["any"] and on_reset:
                on_reset()
            if isinstance(e, ProviderError):
                raise ProviderError(str(e), retryable=True)
            raise ProviderError(f"{kind}: {e}", retryable=True)
    return _route(model, messages, call, num_predict)


def chat_json(
    model: str,
    prompt: str,
    *,
    system: Optional[str] = None,
    temperature: float = 0.0,
    num_predict: int = 768,
    fast: bool = False,
    schema: Optional[Dict[str, Any]] = None,
) -> Any:
    """Chat call in JSON mode; returns the parsed object or raises ValueError."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    raw = chat(model, messages, json_mode=True, temperature=temperature, num_predict=num_predict, fast=fast, schema=schema)
    parsed = parse_llm_json(raw)
    if parsed is None:
        raise ValueError(f"LLM returned non-JSON output: {raw[:160]!r}")
    return parsed


def vision_chat(model: str, prompt: str, image: bytes, *, mime: str = "image/png", num_predict: int = 400) -> str:
    """One question about one image. ``model`` is a hosted spec ("gemini:...") or a local Ollama vision model."""
    kind, name = providers.parse_spec(model)
    if kind == "ollama":
        request = {"model": name, "messages": [{"role": "user", "content": prompt, "images": [image]}],
                   "options": {"temperature": 0.1, "num_predict": num_predict}}
        started = time.perf_counter()
        try:
            resp = get_client().chat(think=False, **request)
        except TypeError:
            resp = get_client().chat(**request)
        providers._record("ollama", name, 0, 0, time.perf_counter() - started)
        return strip_thinking(_field(_field(resp, "message"), "content") or "")
    p = providers.REGISTRY[kind]
    data_url = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt},
                                             {"type": "image_url", "image_url": {"url": data_url}}]}]
    return providers.openai_chat(p, name or p.vision_model, messages, temperature=0.1, max_tokens=num_predict)


# ----------------------------------------------------------------------------
# JSON parsing & repair
# ----------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def _balanced_block(text: str) -> Optional[str]:
    """Returns the first {...} / [...] block (closing it if the output was truncated)."""
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return None
    stack: List[str] = []
    in_str = False
    escaped = False
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
            if not stack:
                return text[start:j + 1]
    # Truncated output: close what is still open.
    tail = text[start:]
    if in_str:
        tail += '"'
    tail = re.sub(r"[,:\s]+$", "", tail)
    return tail + "".join(reversed(stack))


def _salvage(text: str) -> List[str]:
    """
    Repairs for output cut off by the token limit ("...", "category"): besides closing the text
    where it stops, cut it back to each of the last complete elements ({...} or [...]) and close
    it there, so everything before the cut is kept. Empty when the output is complete.
    """
    start = next((i for i, ch in enumerate(text) if ch in "{["), None)
    if start is None:
        return []
    stack: List[str] = []
    cuts: List[Tuple[int, str]] = []  # (end, closers) after each complete nested element
    in_str = escaped = False
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
            if not stack:
                return []
            cuts.append((j + 1, "".join(reversed(stack))))
    tail = text[start:] + ('"' if in_str else "")
    out = [re.sub(r"[,:\s]+$", "", tail) + "".join(reversed(stack))]
    for end, closers in reversed(cuts[-6:]):
        out.append(re.sub(r"[,\s]+$", "", text[start:end]) + closers)
    return out


def _repair(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = re.sub(r",\s*([}\]])", r"\1", s)                       # trailing commas
    s = re.sub(r"(?<![\"\w])True(?![\"\w])", "true", s)          # python literals
    s = re.sub(r"(?<![\"\w])False(?![\"\w])", "false", s)
    s = re.sub(r"(?<![\"\w])None(?![\"\w])", "null", s)
    s = re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", s)                 # invalid escapes (e.g. LaTeX)
    if '"' not in s and "'" in s:                                 # single-quoted pseudo JSON
        s = s.replace("'", '"')
    return s


def parse_llm_json(raw: Optional[str]) -> Any:
    """Best-effort parse of LLM output into JSON. Returns None if nothing parseable is found."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    candidates = [text]
    block = _balanced_block(text)
    if block and block != text:
        candidates.append(block)
    candidates += _salvage(text)
    for cand in candidates:
        for fix in (lambda x: x, _repair):
            try:
                return json.loads(fix(cand), strict=False)
            except Exception:
                continue
    return None


def as_list(value: Any) -> List[Any]:
    """Coerces LLM output that should be a list (None -> [], scalar -> [scalar])."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def as_str_list(value: Any, max_items: int = 50, max_len: int = 300) -> List[str]:
    out = []
    for v in as_list(value):
        if v is None:
            continue
        s = v if isinstance(v, str) else (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
        s = s.strip()
        if s:
            out.append(s[:max_len])
        if len(out) >= max_items:
            break
    return out


# ----------------------------------------------------------------------------
# Numbers: parsing and "does this figure appear in the evidence?"
# ----------------------------------------------------------------------------

_NUM_TOKEN_RE = re.compile(r"(?<![\w.])(-)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\d])")


def to_number(value: Any) -> Optional[float]:
    """Converts LLM-provided values like 1234, "1,234.5", "$3.8", "12%" or "-4" to float."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    if not isinstance(value, str):
        return None
    s = value.strip().replace("−", "-").replace("–", "-")
    s = re.sub(r"[$€£¥₹%\s]", "", s)
    s = s.replace(",", "")
    m = re.match(r"^\(?(-?\d+(?:\.\d+)?)\)?([a-zA-Z]*)$", s)
    if not m:
        return None
    try:
        f = float(m.group(1))
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def extract_numbers(text: str) -> List[float]:
    """All numeric literals in a text (commas removed). Years are included."""
    nums: List[float] = []
    if not text:
        return nums
    for m in _NUM_TOKEN_RE.finditer(text.replace("−", "-")):
        sign, whole, frac = m.group(1), m.group(2), m.group(3) or ""
        try:
            f = float(whole.replace(",", "") + frac)
        except ValueError:
            continue
        if sign:
            start = m.start()
            prev = text[start - 1] if start > 0 else " "
            # "4-7" is a range, not a negative seven.
            if not prev.isdigit():
                f = -f
        nums.append(f)
    return nums


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


_SCALES = {"thousand": 1e3, "million": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9, "trillion": 1e12}
_SCALED_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(thousand|million|billion|trillion|bn|mn)\b", re.IGNORECASE)


def _scaled_numbers(text: str) -> List[float]:
    """Numbers followed directly by a magnitude word: "3.8 million" -> 3800000."""
    out = []
    for m in _SCALED_RE.finditer(text or ""):
        try:
            out.append(float(m.group(1).replace(",", "") + (m.group(2) or "")) * _SCALES[m.group(3).lower()])
        except ValueError:
            continue
    return out


def number_in_text(value: float, text: str, numbers: Optional[List[float]] = None) -> bool:
    """
    True if ``value`` is written in ``text``: exactly, rounded as written, as an absolute
    value, with a magnitude word right after it (3.8 million -> 3800000), or as a
    percentage expressed as a fraction (12% -> 0.12).
    """
    if value is None or not text:
        return False
    numbers = numbers if numbers is not None else extract_numbers(text)
    lowered = text.lower()
    percent = "%" in text or "percent" in lowered
    for n in list(numbers) + _scaled_numbers(text):
        for cand in (n, abs(n)):
            if _close(value, cand) or _close(abs(value), cand):
                return True
            # A fraction standing for a written percentage: 0.17 <-> 17%.
            if percent and abs(value) <= 1.5 and _close(value * 100.0, cand):
                return True
    return False


# ----------------------------------------------------------------------------
# Traces
# ----------------------------------------------------------------------------

def trace(agent: str, status: str, detail: str = "", started: Optional[float] = None, **extra: Any) -> Dict[str, Any]:
    """Builds one ``agent_traces`` entry (JSON-serialisable)."""
    entry: Dict[str, Any] = {"agent": agent, "status": status, "detail": detail, "timestamp": time.time()}
    if started is not None:
        entry["duration_ms"] = int((time.perf_counter() - started) * 1000)
    entry.update(extra)
    return entry
