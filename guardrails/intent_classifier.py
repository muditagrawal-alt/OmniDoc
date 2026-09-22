"""
Multi-Label Semantic Intent Classifier for OmniDoc.
Classifies queries across fine-grained operational categories with confidence scores,
identifying required agent capabilities without keyword matching.
"""
import re
import json
import logging
from typing import Dict, Any, List
import ollama

from core.state import SemanticQuery, IntentClassificationResult

logger = logging.getLogger("OmniDoc.IntentClassifier")

INTENT_CLASSIFICATION_PROMPT = """You are the Multi-Label Intent Classification Engine of OmniDoc.
Analyze the structured SemanticQuery and classify it across primary and secondary intent categories.

Supported Intent Categories:
- factual_retrieval (Specific facts or values)
- semantic_search (Conceptual or thematic queries)
- multi_hop_reasoning (Cross-document or cross-entity inferences)
- graph_traversal (Entity relationship exploration)
- comparison (Comparative evaluation of 2+ entities or periods)
- summarization (Executive summaries, key takeaways)
- numerical_calculation (Percentages, CAGR, arithmetic, formulas)
- statistical_analysis (Distributions, standard deviations, correlations)
- temporal_reasoning (Historical sequences, before/after, timelines)
- document_intelligence (Layout, footnotes, tables, page AST)
- multimodal_analysis (Diagrams, charts, figures inspection)
- visualization (Generating plots, charts, graphs, maps)
- structured_data_analysis (Tabular data, SQL analytics)
- multilingual_query (Queries in non-English or translation requests)
- exploratory_research (Broad open-ended investigations)

Output format (strict JSON):
{{
    "primary_intent": "dominant_category",
    "secondary_intents": ["category2", "category3"],
    "confidence_scores": {{"dominant_category": 0.95, "category2": 0.85}},
    "detected_requirements": ["advanced_hybrid_retrieval", "mathematics_agent", "visualization_agent"]
}}

SEMANTIC QUERY:
{semantic_query_json}
"""


class MultiLabelIntentClassifier:
    """Classifies semantic queries into multi-label intents and required capabilities."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def classify_intent(self, semantic_query: SemanticQuery) -> IntentClassificationResult:
        """Determines multi-label intents and capability requirements."""
        sq_dict = semantic_query.model_dump()

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{
                    "role": "user",
                    "content": INTENT_CLASSIFICATION_PROMPT.format(semantic_query_json=json.dumps(sq_dict, indent=2))
                }],
                options={"temperature": 0.0, "num_predict": 512},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            return IntentClassificationResult(
                primary_intent=parsed.get("primary_intent", "factual_retrieval"),
                secondary_intents=parsed.get("secondary_intents", []),
                confidence_scores=parsed.get("confidence_scores", {"factual_retrieval": 0.85}),
                detected_requirements=parsed.get("detected_requirements", ["advanced_hybrid_retrieval", "synthesis_agent"])
            )

        except Exception as e:
            logger.warning(f"Intent classification fallback triggered ({e}).")
            # Deterministic mapping from semantic_query operations
            primary = "factual_retrieval"
            secondary = []
            reqs = ["advanced_hybrid_retrieval", "synthesis_agent"]
            
            if "calculate" in semantic_query.operations:
                secondary.append("numerical_calculation")
                reqs.append("mathematics_agent")
            if "visualize" in semantic_query.operations:
                secondary.append("visualization")
                reqs.append("visualization_agent")
            if "compare" in semantic_query.operations:
                primary = "comparison"
            if semantic_query.temporal_constraints:
                secondary.append("temporal_reasoning")
                reqs.append("temporal_reasoning_agent")

            return IntentClassificationResult(
                primary_intent=primary,
                secondary_intents=secondary,
                confidence_scores={primary: 0.80},
                detected_requirements=list(set(reqs))
            )

    # Convenience alias
    classify = classify_intent


# Backward-compatible and convenience alias
IntentClassifierAgent = MultiLabelIntentClassifier

