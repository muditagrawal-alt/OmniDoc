"""
Output Guardrail and Groundedness Verifier.

An LLM judge splits the draft answer into factual claims and labels each one supported /
unsupported / contradicted against the SAME numbered evidence list the synthesis agent
cited. ``faithfulness_score`` = supported claims / checked claims. If verification cannot be
performed (LLM unavailable, unparseable output, no claims extracted) the result is
``action="accept"``, ``faithfulness_score=0.0``, ``is_grounded=False`` and the feedback says
the answer is unverified, so the UI can label it honestly instead of showing a made-up score.
"""
import re
import logging
from typing import List, Dict, Any, Optional, Set

from core.state import VerificationResult, EvidencePackage

logger = logging.getLogger("OmniDoc.OutputGuard")

MAX_CLAIMS = 12
REFUSAL_MARKERS = (
    "not found in provided sources",
    "does not contain verifiable records",
    "not mentioned in the document",
)

JUDGE_SYSTEM_PROMPT = """You are an impartial fact-checker for a document question-answering system.
You decide, claim by claim, whether an ANSWER is supported by the NUMBERED EVIDENCE. Use only the evidence; ignore your own knowledge."""

JUDGE_PROMPT = """QUESTION:
{query}

ANSWER TO CHECK:
<<<
{answer}
>>>

NUMBERED EVIDENCE:
{evidence}

Instructions:
1. List the factual claims made IN THE ANSWER above (between <<< and >>>), at most {max_claims}. Take claims only from the answer, never from the evidence. Merge closely related statements; skip headings, transitions and statements that some information is missing.
2. For each claim give a verdict against the evidence:
   - "supported": the evidence states it (paraphrases, unit formatting and simple arithmetic on evidence numbers are fine),
   - "unsupported": the evidence does not state it,
   - "contradicted": the evidence says something different.
3. Give the evidence numbers that support each supported claim.

Return JSON only:
{{"claims": [{{"claim": "claim as worded in the answer", "verdict": "supported", "evidence": [1]}}], "feedback": "one sentence summary"}}"""

_WORD_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
_STOP = {"the", "and", "that", "this", "with", "from", "for", "are", "was", "were", "has", "have", "its", "their",
         "which", "into", "than", "about", "also", "such", "they", "them", "these", "those", "will", "would"}


def _content_words(text: str) -> Set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if (len(w) > 2 or w.isdigit()) and w not in _STOP}


_CITE_MARK_RE = re.compile(r"\[\d{1,3}\]")
_ANSWER_NUM_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\d])(?:\s*(thousand|million|billion|trillion)\b)?",
    re.IGNORECASE,
)
_SCALE_WORDS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}


def stray_numbers(answer: str, evidence_text: str) -> List[str]:
    """
    Numbers the answer states that appear nowhere in the evidence (which includes verified
    calculations), allowing for rounding as written and "3.8 million"-style magnitudes.
    Small whole numbers (list markers, counts up to 12) are ignored.
    """
    from agents.llm_utils import extract_numbers, number_in_text

    evidence_numbers = extract_numbers(evidence_text)
    out: List[str] = []
    for m in _ANSWER_NUM_RE.finditer(_CITE_MARK_RE.sub(" ", answer or "")):
        whole, frac, scale = m.group(1), m.group(2) or "", m.group(3)
        value = float(whole.replace(",", "") + frac)
        decimals = len(frac) - 1 if frac else 0
        if not scale and decimals == 0 and value <= 12:
            continue
        candidates = [value] + ([value * _SCALE_WORDS[scale.lower()]] if scale else [])
        if any(number_in_text(v, evidence_text, evidence_numbers) for v in candidates):
            continue
        tolerance = 0.5 * 10 ** (-decimals)
        if any(abs(c - value) <= tolerance + 1e-12 for c in evidence_numbers):  # rounded as written
            continue
        token = m.group(0).strip()
        if token not in out:
            out.append(token)
    return out[:5]


def _anchored(claim: str, answer_words: Set[str]) -> bool:
    """True when most of the claim's content words occur in the answer (it was taken from the answer)."""
    words = _content_words(claim)
    if not words:
        return False
    return len(words & answer_words) / len(words) >= 0.6


def _unverified(reason: str, cited: List[str]) -> VerificationResult:
    return VerificationResult(
        is_grounded=False,
        faithfulness_score=0.0,
        supported_claims=[],
        unsupported_claims=[],
        cited_sources=cited,
        action="accept",
        feedback=f"Verification unavailable ({reason}); this answer is unverified.",
    )


class OutputGuardrail:
    """Verifies synthesis groundedness and guards against hallucinations."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct", threshold: float = 0.85):
        self.model_name = model_name
        self.threshold = threshold

    def _judge(self, prompt: str) -> Any:
        from agents.llm_utils import chat_json  # local import keeps guardrails importable standalone
        return chat_json(self.model_name, prompt, system=JUDGE_SYSTEM_PROMPT, num_predict=1200)

    def verify(
        self,
        query: str,
        draft_answer: str,
        retrieved_chunks: List[Dict[str, Any]] = None,
        graph_context: List[Dict[str, Any]] = None,
        math_results: List[Dict[str, Any]] = None,
        visual_artifacts: List[Dict[str, Any]] = None,
        conflicts: List[Dict[str, Any]] = None,
        evidence_package: Optional[EvidencePackage] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
        visual_context: Optional[List[Dict[str, Any]]] = None,
        web_context: Optional[List[Dict[str, Any]]] = None,
    ) -> VerificationResult:
        """
        Claim-level groundedness check of ``draft_answer`` against the numbered evidence.
        ``sources`` (the synthesis agent's list) is preferred; otherwise the identical list is
        rebuilt from the evidence inputs.
        """
        from agents.citations import build_sources, format_evidence_block, cited_numbers

        draft_answer = draft_answer or ""
        cited = [str(n) for n in cited_numbers(draft_answer)]

        if not draft_answer.strip():
            return VerificationResult(
                is_grounded=False, faithfulness_score=0.0, unsupported_claims=["Empty response generated"],
                cited_sources=[], action="refine_search", feedback="Draft response is empty.")

        if draft_answer.startswith("Error during synthesis"):
            return _unverified("the answer could not be generated", cited)

        lowered = draft_answer.lower()
        if len(draft_answer) < 400 and any(m in lowered for m in REFUSAL_MARKERS) and not cited:
            return VerificationResult(
                is_grounded=True, faithfulness_score=1.0,
                supported_claims=["The answer states that the documents do not contain the requested information."],
                cited_sources=[], action="accept",
                feedback="Refusal: no factual claims to verify.")

        rebuilt = build_sources(
            evidence_package=evidence_package,
            chunk_context=retrieved_chunks or [],
            graph_context=graph_context or [],
            math_results=math_results or [],
            conflicts=conflicts or [],
            visual_context=visual_context or [],
            web_context=web_context or [],
        )
        if sources:
            # Use the synthesis agent's numbering; take full text from the rebuilt list when it matches.
            by_n = {s["n"]: s for s in rebuilt}
            numbered = []
            for s in sources:
                full = by_n.get(s.get("n"))
                text = full["_text"] if full and full.get("chunk_id") == s.get("chunk_id") else s.get("snippet", "")
                numbered.append(dict(s, _text=text))
        else:
            numbered = rebuilt

        if not numbered:
            return VerificationResult(
                is_grounded=False, faithfulness_score=0.0, unsupported_claims=["No supporting context was retrieved"],
                cited_sources=cited, action="refuse", feedback="Context was empty; the answer cannot be grounded.")

        prompt = JUDGE_PROMPT.format(
            evidence=format_evidence_block(numbered)[:14000],
            query=query,
            answer=draft_answer[:6000],
            max_claims=MAX_CLAIMS,
        )
        try:
            parsed = self._judge(prompt)
        except Exception as e:
            logger.warning(f"Groundedness verification failed: {e}")
            return _unverified(f"verifier error: {str(e)[:120]}", cited)

        claims = parsed.get("claims") if isinstance(parsed, dict) else parsed
        if not isinstance(claims, list):
            return _unverified("verifier returned no claim list", cited)

        supported, unsupported, contradicted = [], [], []
        answer_words = _content_words(draft_answer)
        off_target = 0
        for c in claims[:MAX_CLAIMS]:
            if not isinstance(c, dict):
                continue
            text = str(c.get("claim") or "").strip()
            verdict = str(c.get("verdict") or "").strip().lower()
            if not text or verdict not in ("supported", "unsupported", "contradicted"):
                continue
            if not _anchored(text, answer_words):
                # Small judges sometimes list claims from the evidence instead of the answer.
                off_target += 1
                continue
            if verdict == "supported":
                supported.append(text[:300])
            elif verdict == "contradicted":
                contradicted.append(text[:300])
            else:
                unsupported.append(text[:300])

        # Deterministic net for arithmetic and copying slips the judge lets through.
        evidence_text = "\n".join(
            " ".join(str(x) for x in (s.get("_text") or s.get("snippet") or "", s.get("title") or "",
                                      s.get("section") or "", f"page {s['page']}" if s.get("page") else "") if x)
            for s in numbered
        ) + "\n" + (query or "")
        for token in stray_numbers(draft_answer, evidence_text):
            unsupported.append(f"The number {token} does not appear in the sources or in a verified calculation.")

        checked = len(supported) + len(unsupported) + len(contradicted)
        if checked == 0:
            reason = "the verifier did not check the answer's own claims" if off_target else "no checkable claims were extracted"
            return _unverified(reason, cited)
        if off_target:
            logger.info(f"Output guard ignored {off_target} claim(s) not taken from the answer.")

        score = round(len(supported) / checked, 3)
        problems = unsupported + [f"(contradicted) {c}" for c in contradicted]
        grounded = score >= self.threshold and not contradicted
        action = "accept" if grounded and not unsupported else "refine_search"

        judge_note = str(parsed.get("feedback") or "").strip() if isinstance(parsed, dict) else ""
        if problems:
            feedback = f"{len(problems)} of {checked} claims are not supported by the cited evidence."
        else:
            feedback = f"All {checked} checked claims are supported by the evidence."
        if not cited:
            feedback += " The answer contains no [n] citations."
        if judge_note:
            feedback += f" Verifier note: {judge_note[:300]}"

        return VerificationResult(
            is_grounded=grounded,
            faithfulness_score=score,
            supported_claims=supported,
            unsupported_claims=problems,
            cited_sources=cited,
            action=action,
            feedback=feedback,
        )
