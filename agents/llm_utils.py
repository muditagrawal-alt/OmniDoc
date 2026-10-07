"""
Shared helpers for OmniDoc agents and guardrails:

* one Ollama client with a request timeout and a single, consistent context window
  (changing ``num_ctx`` between calls forces Ollama to reload the model),
* tolerant JSON parsing / repair for LLM output,
* number extraction used to check that figures really come from the evidence,
* a small helper for ``agent_traces`` entries.
"""
import os
import re
import json
import time
import math
import logging
import threading
from typing import Any, Dict, List, Optional

import ollama

logger = logging.getLogger("OmniDoc.LLM")

DEFAULT_NUM_CTX = int(os.getenv("OMNIDOC_NUM_CTX", "8192"))
LLM_TIMEOUT_S = float(os.getenv("OMNIDOC_LLM_TIMEOUT", "300"))

_client = None
_client_lock = threading.Lock()


def get_client() -> "ollama.Client":
    """Lazily creates one shared Ollama client (honours OLLAMA_HOST) with a request timeout."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = ollama.Client(timeout=LLM_TIMEOUT_S)
    return _client


def chat(
    model: str,
    messages: List[Dict[str, str]],
    *,
    json_mode: bool = False,
    temperature: float = 0.0,
    num_predict: int = 512,
    num_ctx: Optional[int] = None,
) -> str:
    """Single non-streaming chat call. Returns the stripped message content (may raise)."""
    options = {
        "temperature": temperature,
        "num_predict": num_predict,
        "num_ctx": num_ctx or DEFAULT_NUM_CTX,
    }
    kwargs: Dict[str, Any] = {}
    if json_mode:
        kwargs["format"] = "json"
    try:
        # Thinking models (qwen3.5, gemma4) otherwise spend the whole token budget
        # thinking and return empty content; models without thinking ignore the flag.
        resp = get_client().chat(model=model, messages=messages, options=options, stream=False, think=False, **kwargs)
    except TypeError:  # ollama client older than 0.5
        resp = get_client().chat(model=model, messages=messages, options=options, stream=False, **kwargs)
    try:
        content = resp["message"]["content"]
    except Exception:
        content = getattr(getattr(resp, "message", None), "content", "")
    return (content or "").strip()


def chat_json(
    model: str,
    prompt: str,
    *,
    system: Optional[str] = None,
    temperature: float = 0.0,
    num_predict: int = 768,
) -> Any:
    """Chat call in Ollama JSON mode; returns the parsed object or raises ValueError."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    raw = chat(model, messages, json_mode=True, temperature=temperature, num_predict=num_predict)
    parsed = parse_llm_json(raw)
    if parsed is None:
        raise ValueError(f"LLM returned non-JSON output: {raw[:160]!r}")
    return parsed


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
