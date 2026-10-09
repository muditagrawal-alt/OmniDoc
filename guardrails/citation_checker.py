"""
Sentence-level citation checking.

The answer is split into sentences (with their character positions). One call to the
local model judges every sentence against the passages that sentence cites, and says which
passages support it if not those. Deterministic checks then override the model where small
models are weakest: every figure in a sentence must appear (allowing for rounding) in a
passage the sentence cites. A sentence that cites the wrong passage gets its citation
corrected in the answer when the right passage contains all of its figures; sentences the
evidence does not support are reported so the interface can mark them.
"""
import re
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("OmniDoc.CitationChecker")

MAX_SENTENCES = 30
CITE_RE = re.compile(r"\[(\d{1,3})\]")
_SKIP_LINE = re.compile(r"^\s*(#{1,6}\s|\||```|~~~|\$\$|>\s*$)")
_ABBREV = re.compile(r"(?:\b(?:[A-Z]|e\.g|i\.e|etc|vs|Dr|Mr|Mrs|Ms|Prof|No|Nos|Fig|Figs|Eq|approx|Inc|Ltd|Pvt|Co|Corp|LLC|LLP|"
                     r"Bros|Govt|Dept|Est|St|Jr|Sr|Rs|Mt|Ft|Vol|vol|pp|al|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|"
                     r"U\.S|U\.K|a\.m|p\.m))\.$")
_NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\d])(?:\s*(thousand|million|billion|trillion)\b)?", re.IGNORECASE)
_SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}

VERDICTS = ("supported", "partial", "unsupported", "contradicted", "no_claim")

JUDGE_PROMPT = """You check an ANSWER sentence by sentence against the numbered evidence it cites.

QUESTION: {query}

SENTENCES:
{sentences}

NUMBERED EVIDENCE:
{evidence}

For every sentence decide, using only the evidence:
- "supported": the passages it cites state it (paraphrase, rounding and simple arithmetic on the passage's numbers are fine),
- "partial": the cited passages support only part of it,
- "unsupported": the cited passages do not state it,
- "contradicted": the cited passages say something different,
- "no_claim": it makes no factual claim (an introduction, a transition, or a statement that information is missing).
In "supported_by" list the evidence numbers that actually support the sentence (they may differ from the ones it cites; empty if none).
Give a short "reason" in your own words.
Return JSON only, for example: {{"sentences": [{{"id": "S1", "verdict": "supported", "supported_by": [2], "reason": "[2] gives the 51% share"}}, {{"id": "S2", "verdict": "unsupported", "supported_by": [], "reason": "no passage mentions 2030"}}]}}"""

# Instructions a small model sometimes copies into the reason instead of writing one.
_PLACEHOLDER_REASONS = {"under 15 words", "short reason", "reason", "[2] gives the 51% share", "no passage mentions 2030"}


def split_sentences(answer: str) -> List[Dict[str, Any]]:
    """
    Sentences of the answer with character offsets and the [n] numbers they cite. Headings,
    table rows, code and display math are skipped; citations written after a sentence's full
    stop are attached to that sentence.
    """
    out: List[Dict[str, Any]] = []
    in_fence = in_math = False
    offset = 0
    for line in answer.splitlines(keepends=True):
        stripped = line.strip()
        start_of_line = offset
        offset += len(line)
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if stripped.startswith("$$"):
            if not (len(stripped) > 4 and stripped.endswith("$$")):  # opens or closes a block
                in_math = not in_math
            continue
        if in_fence or in_math or not stripped or _SKIP_LINE.match(line):
            continue
        body = line.rstrip("\n")
        body = re.sub(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+", lambda m: " " * len(m.group(0)), body)  # list markers
        for s_start, s_end in _sentence_spans(body):
            raw = body[s_start:s_end]
            text = raw.strip()
            if not re.search(r"[^\W\d_]", CITE_RE.sub("", text)):
                # A lone "[2]." belongs to the sentence before it.
                if out and CITE_RE.search(text):
                    out[-1]["citations"] = sorted(set(out[-1]["citations"]) | {int(n) for n in CITE_RE.findall(text)})
                continue
            absolute = start_of_line + s_start + (len(raw) - len(raw.lstrip()))
            out.append({
                "id": f"S{len(out) + 1}",
                "text": text,
                "start": absolute,
                "end": absolute + len(text),
                "citations": sorted({int(n) for n in CITE_RE.findall(text)}),
            })
    return out[:MAX_SENTENCES]


def _sentence_spans(text: str) -> List[Tuple[int, int]]:
    spans, start = [], 0
    for m in re.finditer(r"[.!?](?:\s*\[\d{1,3}\])*(?=\s+[A-Z0-9\"'(\[*]|\s*$)", text):
        end = m.end()
        before = text[max(start, m.start() - 8):m.start() + 1]
        if _ABBREV.search(before):
            continue
        spans.append((start, end))
        start = end
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans


def numbers_in(text: str) -> List[Tuple[str, List[float], int]]:
    """Figures in a sentence: (token, candidate values, decimals). Citations and small counts are skipped."""
    out = []
    clean = CITE_RE.sub(" ", text)
    for m in _NUM_RE.finditer(clean):
        whole, frac, scale = m.group(1), m.group(2) or "", m.group(3)
        value = float(whole.replace(",", "") + frac)
        decimals = len(frac) - 1 if frac else 0
        percent = re.match(r"\s*(%|percent|per cent)", clean[m.end():m.end() + 9], re.I)
        currency = re.search(r"[$€£¥₹]\s*$", clean[max(0, m.start() - 2):m.start()])
        if not scale and not percent and not currency and decimals == 0 and value <= 12:
            continue  # list numbers, counts of things
        values = [value] + ([value * _SCALES[scale.lower()]] if scale else [])
        token = m.group(0).strip()
        if percent:
            token += "%" if percent.group(1) == "%" else f" {percent.group(1)}"
        if currency:
            token = currency.group(0).strip() + token
        out.append((token, values, decimals))
    return out


def figure_supported(values: List[float], decimals: int, text: str, text_numbers: List[float]) -> bool:
    from agents.llm_utils import number_in_text
    if any(number_in_text(v, text, text_numbers) for v in values):
        return True
    tolerance = 0.5 * 10 ** (-decimals)
    return any(abs(c - values[0]) <= tolerance + 1e-12 for c in text_numbers)


def check_sentences(
    answer: str,
    query: str,
    sources: Sequence[Dict[str, Any]],
    judge: Optional[Callable[[str], Any]] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Returns (sentence checks, corrected answer). Each check has id, text, start, end,
    citations, verdict, supported_by, reason, and "corrected_to" when its citation was fixed.
    """
    from agents.llm_utils import extract_numbers

    sentences = split_sentences(answer)
    if not sentences:
        return [], answer
    by_n = {s["n"]: s for s in sources}
    # Figures may also come from a source's metadata ("described on page 47").
    texts = {n: " ".join(str(v) for v in (s.get("_text") or s.get("snippet") or "", s.get("title") or "", s.get("section") or "",
                                          f"page {s['page']}" if s.get("page") else "") if v)
             for n, s in by_n.items()}
    numbers = {n: extract_numbers(t) for n, t in texts.items()}

    verdicts: Dict[str, Dict[str, Any]] = {}
    if judge is not None:
        from agents.citations import format_evidence_block
        listing = "\n".join(
            f"{s['id']} (cites {''.join(f'[{n}]' for n in s['citations']) or 'nothing'}): {CITE_RE.sub('', s['text']).strip()}"
            for s in sentences)
        try:
            parsed = judge(JUDGE_PROMPT.format(query=query[:600], sentences=listing,
                                               evidence=format_evidence_block(list(sources))[:14000]))
            for item in (parsed.get("sentences") or [] if isinstance(parsed, dict) else []):
                if isinstance(item, dict) and str(item.get("id", "")).strip() in {s["id"] for s in sentences}:
                    verdicts[str(item["id"]).strip()] = item
        except Exception as e:
            logger.warning(f"Sentence judge failed: {e}")

    checks = []
    for s in sentences:
        item = verdicts.get(s["id"], {})
        verdict = str(item.get("verdict") or "").strip().lower()
        verdict = verdict if verdict in VERDICTS else ("unchecked" if judge is None or not verdicts else "unsupported")
        supported_by = sorted({int(n) for n in (item.get("supported_by") or []) if str(n).isdigit() and int(n) in by_n})
        reason = str(item.get("reason") or "").strip()[:200]
        if reason.lower().strip(" .") in _PLACEHOLDER_REASONS:
            reason = ""
        cited = [n for n in s["citations"] if n in by_n]

        # Every figure must appear in a passage the sentence cites. A figure found only in an
        # uncited passage means the citation is wrong; a figure found nowhere is unsupported.
        figures = numbers_in(s["text"])
        needed: List[int] = []
        missing: List[str] = []
        for token, values, decimals in figures:
            holders = [n for n in by_n if figure_supported(values, decimals, texts[n], numbers[n])]
            in_cited = [n for n in cited if n in holders]
            if in_cited:
                needed.append(in_cited[0])
            elif holders:
                preferred = [n for n in supported_by if n in holders]
                needed.append((preferred or holders)[0])
            else:
                missing.append(token)
        if missing and verdict not in ("no_claim",):
            verdict = "unsupported"
            reason = f"{', '.join(missing[:3])} does not appear in the evidence."
        check = {**s, "verdict": verdict, "supported_by": supported_by, "reason": reason}
        if not missing and verdict in ("supported", "partial", "unchecked"):
            wanted = sorted(set(needed) | ({n for n in supported_by} if not figures else set()))
            if figures and not set(needed) <= set(cited):
                check["corrected_to"] = sorted(set(needed) | (set(cited) & set(supported_by)))[:3]
                check["reason"] = reason or "The figures appear in a different passage."
                if verdict == "unchecked":
                    check["verdict"] = "supported"
            elif not figures and verdict in ("supported", "partial") and supported_by and not (set(supported_by) & set(cited)):
                check["corrected_to"] = wanted[:2]
        checks.append(check)
    return checks, _apply_corrections(answer, checks)


def _apply_corrections(answer: str, checks: List[Dict[str, Any]]) -> str:
    """Rewrites the citation markers of corrected sentences (later sentences first, so offsets stay valid)."""
    out = answer
    for c in sorted(checks, key=lambda c: c["start"], reverse=True):
        new = c.get("corrected_to")
        if not new:
            continue
        segment = out[c["start"]:c["end"]]
        markers = "".join(f"[{n}]" for n in new)
        if CITE_RE.search(segment):
            replaced = CITE_RE.sub("", segment)
            replaced = re.sub(r"\s+([.!?])$", r"\1", replaced.rstrip())
            # Put the corrected markers before the closing punctuation, as the writer does.
            m = re.search(r"([.!?])$", replaced)
            fixed = replaced[:m.start()] + " " + markers + m.group(1) if m else replaced + " " + markers
        else:
            m = re.search(r"([.!?])$", segment)
            fixed = segment[:m.start()] + " " + markers + m.group(1) if m else segment + " " + markers
        fixed = re.sub(r"\s{2,}", " ", fixed)
        out = out[:c["start"]] + fixed + out[c["end"]:]
        delta = len(fixed) - (c["end"] - c["start"])
        c["end"] += delta
        c["text"] = fixed
        c["citations"] = list(new)
        for later in checks:  # sentences after this one moved by delta
            if later is not c and later["start"] > c["start"]:
                later["start"] += delta
                later["end"] += delta
    return out


def summarise(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts and a faithfulness score over sentences that make claims."""
    judged = [c for c in checks if c["verdict"] not in ("no_claim", "unchecked")]
    weights = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0, "contradicted": 0.0}
    score = sum(weights.get(c["verdict"], 0.0) for c in judged) / len(judged) if judged else None
    return {
        "checked": len(judged),
        "supported": sum(c["verdict"] == "supported" for c in judged),
        "partial": sum(c["verdict"] == "partial" for c in judged),
        "unsupported": sum(c["verdict"] in ("unsupported", "contradicted") for c in judged),
        "corrected": sum(bool(c.get("corrected_to")) for c in checks),
        "score": None if score is None else round(score, 3),
    }
