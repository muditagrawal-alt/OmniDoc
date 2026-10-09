"""
Multilingual Agent for OmniDoc.

Decides the language of the question and of the answer without translating documents:
the question's language comes from its writing system (Devanagari, Tamil, Bengali, ...)
or from the understanding step; the answer language is the one picked in the interface,
else the question's. Questions in another language than the documents are searched with
the English queries written by the understanding step (cross-lingual retrieval), and the
writer is told which language to answer in.
"""
import logging
from typing import Any, Dict, Optional

from agents.understanding_agent import detect_script_language

logger = logging.getLogger("OmniDoc.MultilingualAgent")

LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "kn": "Kannada", "bn": "Bengali",
    "as": "Assamese", "gu": "Gujarati", "pa": "Punjabi", "ml": "Malayalam", "or": "Odia", "ur": "Urdu", "fr": "French",
    "de": "German", "es": "Spanish", "pt": "Portuguese", "it": "Italian", "ru": "Russian", "zh": "Chinese",
    "ja": "Japanese", "ko": "Korean", "ar": "Arabic",
}


class MultilingualAgent:
    """Detects the question's language and decides the answer language."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def languages(query: str, understanding: Dict[str, Any], requested: Optional[str] = None) -> Dict[str, str]:
        """{"question": code, "answer": code, "answer_name": name}."""
        script = detect_script_language(query)
        question = script if script != "en" else (understanding.get("language") or "en")
        answer = requested or question
        return {"question": question, "answer": answer, "answer_name": LANGUAGE_NAMES.get(answer, answer)}

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Stand-alone node form (the workflow calls ``languages`` from the understanding step)."""
        semantic_q = state.get("semantic_query")
        langs = self.languages(state.get("user_query", ""), {"language": getattr(semantic_q, "language", "en")},
                               state.get("answer_language") or None)
        logger.info(f"MultilingualAgent: question {langs['question']}, answer {langs['answer']}.")
        return {"answer_language": langs["answer"]}
