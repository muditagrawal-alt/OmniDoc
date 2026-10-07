"""
Multi-Label Semantic Intent Classifier for OmniDoc.
Classifies queries across fine-grained operational categories with confidence scores and
identifies required agent capabilities.

It is also the workflow's scope gate (the workflow rejects when ``is_in_scope`` is False).
Only clear prompt-injection / jailbreak *instructions* are rejected; questions *about*
security, attacks, medicine, politics, violence etc. are legitimate document questions and
are always allowed. LLM failures never reject a query.
"""
import re
import json
import logging
from typing import Dict, Any, List, Optional

from core.state import SemanticQuery, IntentClassificationResult

logger = logging.getLogger("OmniDoc.IntentClassifier")

INTENT_CATEGORIES = [
    "factual_retrieval", "semantic_search", "multi_hop_reasoning", "graph_traversal", "comparison",
    "summarization", "numerical_calculation", "statistical_analysis", "temporal_reasoning",
    "document_intelligence", "multimodal_analysis", "visualization", "structured_data_analysis",
    "multilingual_query", "exploratory_research",
]

INTENT_CLASSIFICATION_PROMPT = """You are the Multi-Label Intent Classification Engine of OmniDoc.
Analyze the structured SemanticQuery and classify it across primary and secondary intent categories.

Supported Intent Categories:
- factual_retrieval (Specific facts or values)
- semantic_search (Conceptual or thematic queries)
- multi_hop_reasoning (Cross-document or cross-entity inferences)
- graph_traversal (Entity relationship exploration)
- comparison (Comparative evaluation of 2+ entities or periods)
- summarization (Executive summaries, key takeaways)
- numerical_calculation (Percentages, growth rates, arithmetic, formulas)
- statistical_analysis (Distributions, standard deviations, correlations)
- temporal_reasoning (Historical sequences, before/after, timelines)
- document_intelligence (Layout, footnotes, tables, page structure)
- multimodal_analysis (Diagrams, charts, figures inspection)
- visualization (The user explicitly asks for a plot, chart, graph or other visual)
- structured_data_analysis (Tabular data, SQL analytics)
- multilingual_query (Queries in non-English or translation requests)
- exploratory_research (Broad open-ended investigations)

Capabilities for "detected_requirements":
- "advanced_hybrid_retrieval": always.
- "knowledge_graph_agent": relationships between entities, multi-hop questions.
- "mathematics_agent": ONLY if arithmetic must be performed (growth, difference, ratio, percentage, statistics).
- "visualization_agent": ONLY if the user explicitly asks for a chart, plot, graph or visual.
- "vision_agent": ONLY if the question is about figures, diagrams or images.

Output format (strict JSON):
{{"primary_intent": "factual_retrieval", "secondary_intents": [], "confidence_scores": {{"factual_retrieval": 0.9}}, "detected_requirements": ["advanced_hybrid_retrieval"]}}

SEMANTIC QUERY:
{semantic_query_json}
"""

# ----------------------------------------------------------------------------
# Prompt-injection / jailbreak detection (precise, imperative-only patterns)
# ----------------------------------------------------------------------------

_SENTENCE_START = r"(?:^|[.!?;:\n]\s*|\b(?:now|please|and|then|also)\s+)"
PROMPT_INJECTION_PATTERNS = [
    # "Ignore all previous instructions ..." issued as a command (not quoted / asked about).
    _SENTENCE_START + r"(?:please\s+)?(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|every\s+)?(?:of\s+)?(?:your\s+|the\s+|my\s+)?"
    r"(?:previous|prior|above|earlier|preceding|system|original|safety)\s+(?:instructions?|prompts?|rules|guidelines|directives|guardrails)\b",
    r"\byou\s+are\s+now\s+(?:an?\s+)?(?:unrestricted|unfiltered|uncensored|jailbroken|dan)\b",
    r"\b(?:enable|activate|enter|switch\s+(?:to|into)|turn\s+on)\s+(?:the\s+)?(?:dan|developer|jailbreak|god|unrestricted)\s+mode\b",
    r"\bact\s+as\s+(?:an?\s+)?(?:unrestricted|unfiltered|uncensored|jailbroken)\s+(?:ai|model|assistant|chatbot)\b",
    r"\b(?:reveal|print|output|show|repeat|leak|dump)\s+(?:me\s+)?your\s+(?:system\s+prompt|hidden\s+instructions|initial\s+instructions|instructions\s+verbatim)\b",
    _SENTENCE_START + r"(?:bypass|disable|turn\s+off)\s+(?:all\s+)?(?:your\s+|the\s+)?(?:safety\s+)?(?:filters|guardrails|safety\s+rules|content\s+policy)\b",
    r"\bsystem\s*:\s*override\b",
]
_COMPILED_INJECTION = [re.compile(p, re.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]
_QUOTED_SPAN = re.compile(r"\"[^\"]*\"|“[^”]*”|'[^']{8,}'")


def detect_prompt_injection(query: str) -> Optional[str]:
    """
    Returns a rejection reason if the query *issues* an instruction-override / jailbreak
    command. Quoted text is ignored so users can ask about such phrases in their documents.
    """
    if not query:
        return None
    unquoted = _QUOTED_SPAN.sub(" ", query)
    for pattern in _COMPILED_INJECTION:
        if pattern.search(unquoted):
            return "Security violation: the request tries to override the assistant's instructions (prompt injection / jailbreak)."
    return None


def _float(v: Any, default: float) -> float:
    try:
        f = float(v)
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return default


def _str_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return [str(x).strip() for x in v if isinstance(x, (str, int, float)) and str(x).strip()]


class MultiLabelIntentClassifier:
    """Classifies semantic queries into multi-label intents and required capabilities."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def _fallback(self, semantic_query: SemanticQuery) -> IntentClassificationResult:
        """Deterministic mapping from the semantic query's operations."""
        primary = "factual_retrieval"
        secondary: List[str] = []
        reqs = ["advanced_hybrid_retrieval", "synthesis_agent"]
        ops = set(semantic_query.operations or [])
        if "calculate" in ops:
            secondary.append("numerical_calculation")
            reqs.append("mathematics_agent")
        if "visualize" in ops or "chart" in (semantic_query.output_requirements or []):
            secondary.append("visualization")
            reqs.append("visualization_agent")
        if "compare" in ops:
            primary = "comparison"
        elif "summarize" in ops:
            primary = "summarization"
        if semantic_query.temporal_constraints:
            secondary.append("temporal_reasoning")
        return IntentClassificationResult(
            primary_intent=primary,
            secondary_intents=secondary,
            confidence_scores={primary: 0.6},
            detected_requirements=list(dict.fromkeys(reqs)),
            confidence=0.6,
        )

    def classify_intent(self, semantic_query: SemanticQuery) -> IntentClassificationResult:
        """Determines multi-label intents and capability requirements."""
        injection = detect_prompt_injection(semantic_query.raw_query or semantic_query.resolved_query or "")
        if injection:
            logger.warning(f"Prompt injection blocked: '{(semantic_query.raw_query or '')[:80]}'")
            return IntentClassificationResult(
                primary_intent="prompt_injection",
                confidence_scores={"prompt_injection": 1.0},
                is_in_scope=False,
                rejection_reason=injection,
                confidence=1.0,
            )

        try:
            from agents.llm_utils import chat_json  # local import keeps guardrails importable standalone
            sq_dict = semantic_query.model_dump()
            parsed = chat_json(
                self.model_name,
                INTENT_CLASSIFICATION_PROMPT.format(semantic_query_json=json.dumps(sq_dict, indent=2, default=str)),
                num_predict=300,
            )
            if not isinstance(parsed, dict):
                raise ValueError("expected a JSON object")
            primary = str(parsed.get("primary_intent") or "factual_retrieval").strip()
            if primary not in INTENT_CATEGORIES:
                primary = "factual_retrieval"
            secondary = [s for s in _str_list(parsed.get("secondary_intents")) if s in INTENT_CATEGORIES and s != primary]
            scores_raw = parsed.get("confidence_scores")
            scores = {}
            if isinstance(scores_raw, dict):
                scores = {str(k): _float(v, 0.5) for k, v in scores_raw.items() if str(k) in INTENT_CATEGORIES}
            reqs = _str_list(parsed.get("detected_requirements")) or ["advanced_hybrid_retrieval"]
            # Requirements must agree with the semantic analysis (avoid spurious math / charts).
            ops = set(semantic_query.operations or [])
            wants_chart = "visualize" in ops or "chart" in (semantic_query.output_requirements or []) or "visualization" in secondary or primary == "visualization"
            if not wants_chart:
                reqs = [r for r in reqs if "visual" not in r.lower() and "chart" not in r.lower()]
            return IntentClassificationResult(
                primary_intent=primary,
                secondary_intents=secondary,
                confidence_scores=scores or {primary: 0.8},
                detected_requirements=list(dict.fromkeys(reqs)),
                confidence=scores.get(primary, 0.8),
            )
        except Exception as e:
            logger.warning(f"Intent classification fallback triggered ({e}).")
            return self._fallback(semantic_query)

    # Convenience alias
    classify = classify_intent


# Backward-compatible and convenience alias
IntentClassifierAgent = MultiLabelIntentClassifier
