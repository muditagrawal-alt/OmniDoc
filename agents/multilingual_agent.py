"""
Multilingual Agent for OmniDoc.
Provides language detection, cross-lingual retrieval mapping,
and target language formatting without unnecessary full-text translation.
"""
import logging
from typing import Dict, Any
from core.state import AgentWorkflowState

logger = logging.getLogger("OmniDoc.MultilingualAgent")


class MultilingualAgent:
    """Detects query language and manages cross-lingual alignment."""

    def __init__(self):
        pass

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Detects language and adds target language directive if non-English."""
        query = state.get("user_query", "")
        semantic_q = state.get("semantic_query")
        
        lang = semantic_q.language if semantic_q else "en"
        
        # Simple heuristic check for Devanagari or other common scripts
        if any('\u0900' <= ch <= '\u097F' for ch in query):
            lang = "hi"
            if semantic_q:
                semantic_q.language = "hi"
                
        logger.info(f"MultilingualAgent: Detected language '{lang}'.")
        return {
            "chunk_context": [{"detected_language": lang}]
        }
