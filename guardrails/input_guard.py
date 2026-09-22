"""
Input Guardrail and Security Boundary for OmniDoc.
Screens incoming user queries for adversarial prompt injections and security violations.
Delegates natural language understanding and intent classification to the Semantic NLU layer.
"""
import re
import logging
from typing import Optional, Tuple

from core.state import QueryIntentContract, QueryIntentType, SemanticQuery
from guardrails.semantic_nlu import SemanticNLUEngine
from guardrails.intent_classifier import MultiLabelIntentClassifier

logger = logging.getLogger("OmniDoc.InputGuard")

PROMPT_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"(?i)disregard\s+(all\s+)?(previous|prior|system)\s+prompts?",
    r"(?i)you\s+are\s+now\s+(an?\s+)?unrestricted",
    r"(?i)jailbreak",
    r"(?i)dan\s+mode",
    r"(?i)bypass\s+all\s+(filters|rules|guardrails)",
    r"(?i)system\s*:\s*override",
    r"(?i)output\s+(the\s+)?system\s+prompt",
]


class InputGuardrail:
    """Validates query safety and boundaries, then routes to Semantic NLU."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name
        self.nlu_engine = SemanticNLUEngine(model_name)
        self.intent_classifier = MultiLabelIntentClassifier(model_name)

    def check_prompt_injection(self, query: str) -> Optional[str]:
        """Detects adversarial jailbreak attempts."""
        for pattern in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, query):
                return "Security violation: query attempted prompt injection or instruction override."
        return None

    def validate_and_parse(self, query: str, conversation_history: list = None) -> Tuple[bool, Optional[str], Optional[SemanticQuery]]:
        """
        Validates safety and extracts semantic understanding without keyword matching.
        Returns: (is_allowed, error_reason, semantic_query)
        """
        injection_err = self.check_prompt_injection(query)
        if injection_err:
            logger.warning(f"🚨 Prompt injection blocked: '{query[:60]}...'")
            return False, injection_err, None

        # Deep semantic understanding
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

        # Map semantic_q to backward-compatible contract
        intent_res = self.intent_classifier.classify_intent(semantic_q)
        
        # Determine requirements based on semantic operations
        req_graph = "graph_traversal" in intent_res.secondary_intents or "multi_hop_reasoning" in intent_res.secondary_intents
        req_vector = True
        req_vision = "multimodal_analysis" in intent_res.secondary_intents or "visual" in semantic_q.modality_requirements
        req_math = "numerical_calculation" in intent_res.secondary_intents or "calculate" in semantic_q.operations

        primary = QueryIntentType.FACTUAL_LOOKUP
        if "comparison" in intent_res.primary_intent:
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
            confidence=intent_res.confidence_scores.get(intent_res.primary_intent, 0.85),
            entities_mentioned=semantic_q.entities,
            sub_questions=semantic_q.sub_questions,
            requires_graph=req_graph,
            requires_vector=req_vector,
            requires_vision=req_vision,
            requires_web=False,
            is_in_scope=True,
            rejection_reason=None
        )
