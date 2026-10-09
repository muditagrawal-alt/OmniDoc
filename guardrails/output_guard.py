"""
Output Guardrail and Groundedness Verifier.

Checks the draft answer sentence by sentence against the SAME numbered evidence list the
synthesis agent cited (see guardrails/citation_checker.py): every sentence is judged against
the passages it cites, figures must appear in a cited passage, and citations that point at
the wrong passage are corrected. ``faithfulness_score`` is the share of claim-making
sentences that are supported (partial support counts half). If verification cannot be
performed (LLM unavailable, unparseable output) the result is ``action="accept"``,
``faithfulness_score=0.0``, ``is_grounded=False`` and the feedback says the answer is
unverified, so the UI can label it honestly instead of showing a made-up score.
"""
import re
import logging
from typing import List, Dict, Any, Optional, Set

from core.state import VerificationResult, EvidencePackage

logger = logging.getLogger("OmniDoc.OutputGuard")

REFUSAL_MARKERS = (
    "not found in provided sources",
    "does not contain verifiable records",
    "not mentioned in the document",
)

JUDGE_SYSTEM_PROMPT = """You are an impartial fact-checker for a document question-answering system.
You decide, sentence by sentence, whether an answer is supported by the numbered evidence it cites. Use only the evidence; ignore your own knowledge."""

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
        return chat_json(self.model_name, prompt, system=JUDGE_SYSTEM_PROMPT, num_predict=1500)

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
        table_results: Optional[List[Dict[str, Any]]] = None,
        summary_context: Optional[List[Dict[str, Any]]] = None,
    ) -> VerificationResult:
        """
        Sentence-level groundedness check of ``draft_answer`` against the numbered evidence.
        ``sources`` (the synthesis agent's list) is preferred; otherwise the identical list is
        rebuilt from the evidence inputs.
        """
        from agents.citations import build_sources, cited_numbers

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
            table_results=table_results or [],
            summary_context=summary_context or [],
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

        from guardrails.citation_checker import check_sentences, summarise

        checks, corrected = check_sentences(draft_answer, query, numbered, judge=self._judge)
        counts = summarise(checks)
        sentences = [{k: c.get(k) for k in ("id", "text", "start", "end", "citations", "verdict", "supported_by",
                                            "reason", "corrected_to")} for c in checks]
        judged = [c for c in checks if c["verdict"] != "unchecked"]
        if not judged:
            result = _unverified("the verifier did not respond", cited)
            result.sentences = sentences
            return result

        supported = [c["text"][:300] for c in checks if c["verdict"] == "supported"]
        problems = [c["text"][:300] + (f" ({c['reason']})" if c.get("reason") else "")
                    for c in checks if c["verdict"] in ("unsupported", "contradicted")]
        contradicted = any(c["verdict"] == "contradicted" for c in checks)
        checked = counts["checked"]
        if checked == 0:
            return VerificationResult(
                is_grounded=True, faithfulness_score=1.0, supported_claims=[], unsupported_claims=[],
                cited_sources=cited, action="accept", feedback="The answer makes no factual claims to verify.",
                sentences=sentences)

        score = counts["score"] if counts["score"] is not None else 0.0
        grounded = score >= self.threshold and not contradicted
        action = "accept" if not problems else "refine_search"
        if problems:
            feedback = f"{len(problems)} of {checked} sentences are not supported by the passages they cite."
        else:
            feedback = f"All {checked} checked sentences are supported by the passages they cite."
        if counts["partial"]:
            feedback += f" {counts['partial']} only partly."
        if counts["corrected"]:
            feedback += f" Corrected the citation of {counts['corrected']} sentence(s)."
        if not cited:
            feedback += " The answer contains no [n] citations."

        return VerificationResult(
            is_grounded=grounded,
            faithfulness_score=score,
            supported_claims=supported,
            unsupported_claims=problems,
            cited_sources=[str(n) for n in sorted({n for c in checks for n in c["citations"]})] or cited,
            action=action,
            feedback=feedback,
            sentences=sentences,
            corrected_answer=corrected if corrected != draft_answer else None,
        )
