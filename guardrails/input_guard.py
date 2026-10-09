"""
Input Guardrail and Security Boundary for OmniDoc.
Screens incoming user queries for prompt-injection / jailbreak commands, then delegates
natural language understanding and intent classification to the Semantic NLU layer.

Only explicit instruction-override commands are blocked; questions about sensitive topics
(security, attacks, medicine, politics, ...) that may appear in the user's documents are
always allowed. The same detector is applied inside the workflow by the intent classifier.
"""
import logging
from typing import Optional, Tuple

from core.state import QueryIntentContract, QueryIntentType, SemanticQuery
from guardrails.semantic_nlu import SemanticNLUEngine
from guardrails.intent_classifier import (
    MultiLabelIntentClassifier,
    PROMPT_INJECTION_PATTERNS,  # re-exported for backward compatibility
    detect_prompt_injection,
)

logger = logging.getLogger("OmniDoc.InputGuard")

MAX_QUERY_CHARS = 8000

__all__ = ["InputGuardrail", "PROMPT_INJECTION_PATTERNS", "detect_prompt_injection"]


class InputGuardrail:
    """Validates query safety and boundaries, then routes to Semantic NLU."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name
        self.nlu_engine = SemanticNLUEngine(model_name)
        self.intent_classifier = MultiLabelIntentClassifier(model_name)

    @staticmethod
    def screen(query: str) -> Optional[str]:
        """
        The first step of every question, without a model call: rejects empty or oversized
        input and explicit instruction-override (prompt-injection) commands. Returns the
        reason, or None when the question may proceed.
        """
        text = (query or "").strip()
        if not text:
            return "The question is empty."
        if len(text) > MAX_QUERY_CHARS:
            return f"The question is too long ({len(text)} characters; the limit is {MAX_QUERY_CHARS})."
        if len(set(text)) <= 2 and len(text) > 50:
            return "The question has no readable content."
        return detect_prompt_injection(text)

    def check_prompt_injection(self, query: str) -> Optional[str]:
        """Detects adversarial jailbreak / instruction-override commands."""
        return detect_prompt_injection(query or "")

    def validate_and_parse(self, query: str, conversation_history: list = None) -> Tuple[bool, Optional[str], Optional[SemanticQuery]]:
        """
        Validates safety and extracts semantic understanding.
        Returns: (is_allowed, error_reason, semantic_query)
        """
        if not query or not query.strip():
            return False, "Empty query.", None
        if len(query) > MAX_QUERY_CHARS:
            return False, f"Query is too long ({len(query)} characters; limit {MAX_QUERY_CHARS}).", None
        injection_err = self.check_prompt_injection(query)
        if injection_err:
            logger.warning(f"Prompt injection blocked: '{query[:60]}...'")
            return False, injection_err, None

        semantic_q = self.nlu_engine.understand_query(raw_query=query)
        return True, None, semantic_q

    def classify_and_guard(self, query: str) -> QueryIntentContract:
        """Backward-compatible contract adapter."""
        is_safe, error, semantic_q = self.validate_and_parse(query)
        if not is_safe:
            return QueryIntentContract(
                raw_query=query,
                refined_query=query,
                intent=QueryIntentType.OUT_OF_SCOPE,
                confidence=1.0,
                is_in_scope=False,
                rejection_reason=error,
                requires_graph=False,
                requires_vector=False,
                requires_vision=False,
                requires_web=False
            )

        intent_res = self.intent_classifier.classify_intent(semantic_q)
        req_graph = intent_res.requires_graph or bool({"graph_traversal", "multi_hop_reasoning"} & set(intent_res.secondary_intents))
        req_vision = intent_res.requires_vision or "visual" in semantic_q.modality_requirements

        primary = QueryIntentType.FACTUAL_LOOKUP
        if not intent_res.is_in_scope:
            primary = QueryIntentType.OUT_OF_SCOPE
        elif "comparison" in intent_res.primary_intent:
            primary = QueryIntentType.COMPARATIVE_AUDIT
        elif "summarization" in intent_res.primary_intent:
            primary = QueryIntentType.DEEP_SUMMARY
        elif req_graph:
            primary = QueryIntentType.MULTI_HOP_RELATIONAL
        elif req_vision:
            primary = QueryIntentType.VISUAL_DIAGRAM

        return QueryIntentContract(
            raw_query=query,
            refined_query=semantic_q.resolved_query,
            intent=primary,
            confidence=intent_res.confidence_scores.get(intent_res.primary_intent, intent_res.confidence),
            entities_mentioned=semantic_q.entities,
            sub_questions=semantic_q.sub_questions,
            requires_graph=req_graph,
            requires_vector=True,
            requires_vision=req_vision,
            requires_web=False,
            is_in_scope=intent_res.is_in_scope,
            rejection_reason=intent_res.rejection_reason
        )
