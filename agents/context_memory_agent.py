"""
Context Resolution and Memory Agent for OmniDoc.
Resolves conversational anaphora, pronouns, and references across turns.
Maintains a compact structured conversation memory state.
"""
import json
import time
import logging
from typing import Dict, Any, List, Optional, Tuple

from core.state import ConversationMemoryState, AgentWorkflowState
from agents.llm_utils import chat_json, as_str_list, trace

logger = logging.getLogger("OmniDoc.ContextMemoryAgent")

CONTEXT_RESOLUTION_PROMPT = """You are the Context Resolution & Conversational Memory Agent of OmniDoc.
Your job is to resolve pronouns and references in the LATEST USER QUERY using the CONVERSATION HISTORY and ACTIVE MEMORY.

References to resolve include:
- "it", "they", "them", "their", "this", "that"
- "this company", "that report", "the previous document"
- "same period", "that year", "then"
- "the above result", "the second one", "both of them"

Rules:
1. If the latest query refers to earlier context, rewrite it into a self-contained question that names what is referred to (take names only from the history; never add new facts).
2. If the query is ALREADY self-contained, return it unchanged.
3. The rewrite must stay a question/request from the user; never answer it.
4. Output ONLY valid JSON:
{{"resolved_query": "self-contained query", "active_entities": ["..."], "active_time_range": "string or null", "active_topic": "string or null", "references_resolved": ["<reference> -> <what it refers to>"]}}

ACTIVE MEMORY STATE:
{active_memory}

RECENT CONVERSATION HISTORY:
{history}

LATEST USER QUERY:
{query}
"""


class ContextResolutionAgent:
    """Resolves multi-turn conversational references and manages thread memory."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    @staticmethod
    def _history_text(conversation_history: List[Dict[str, str]]) -> str:
        lines = []
        for turn in (conversation_history or [])[-6:]:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", "user")).capitalize()
            content = " ".join(str(turn.get("content", "")).split())
            limit = 300 if role.lower() == "user" else 600
            lines.append(f"{role}: {content[:limit]}")
        return "\n".join(lines)

    @staticmethod
    def _plausible(resolved: Any, original: str) -> bool:
        if not isinstance(resolved, str) or not resolved.strip():
            return False
        # A rewrite that is far longer than the question is usually an answer, not a question.
        return len(resolved) <= max(3 * len(original), len(original) + 250)

    def resolve_context(
        self,
        current_query: str,
        conversation_history: List[Dict[str, str]],
        memory_state: Optional[ConversationMemoryState] = None
    ) -> Tuple[str, ConversationMemoryState]:
        """
        Resolves references in the current query and updates structured memory.
        """
        state = memory_state.model_copy(deep=True) if memory_state else ConversationMemoryState()
        if not conversation_history and not state.active_entities:
            state.previous_queries = (state.previous_queries + [current_query])[-10:]
            return current_query, state

        prompt = CONTEXT_RESOLUTION_PROMPT.format(
            active_memory=json.dumps(state.model_dump(), indent=2),
            history=self._history_text(conversation_history) or "None",
            query=current_query,
        )
        try:
            parsed = chat_json(self.model_name, prompt, num_predict=400)
            if not isinstance(parsed, dict):
                raise ValueError("expected a JSON object")
            resolved = parsed.get("resolved_query")
            if not self._plausible(resolved, current_query):
                logger.info(f"Context resolution produced an implausible rewrite ({str(resolved)[:80]!r}); keeping original.")
                resolved = current_query
            resolved = resolved.strip()

            new_entities = as_str_list(parsed.get("active_entities"), max_items=10, max_len=120)
            merged = list(dict.fromkeys(state.active_entities + new_entities))
            state.active_entities = merged[-10:]
            tr = parsed.get("active_time_range")
            if isinstance(tr, str) and tr.strip() and tr.lower() != "null":
                state.active_time_range = tr.strip()[:80]
            topic = parsed.get("active_topic")
            if isinstance(topic, str) and topic.strip() and topic.lower() != "null":
                state.active_topic = topic.strip()[:120]
            state.unresolved_references = []
            state.previous_queries = (state.previous_queries + [current_query])[-10:]
            logger.info(f"Context Resolution: '{current_query}' -> '{resolved}'")
            return resolved, state
        except Exception as e:
            logger.warning(f"Context resolution fallback triggered ({e}).")
            state.previous_queries = (state.previous_queries + [current_query])[-10:]
            return current_query, state

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """LangGraph node execution wrapper."""
        started = time.perf_counter()
        query = state.get("user_query", "")
        history = state.get("conversation_history", [])
        mem_state = state.get("memory_state")
        resolved, updated_mem = self.resolve_context(query, history, mem_state)
        detail = f"'{query[:80]}' -> '{resolved[:80]}'" if resolved != query else "Query already self-contained."
        return {
            "user_query": resolved,
            "memory_state": updated_mem,
            "agent_traces": [trace("context_resolution", "completed", detail, started)],
        }


# Backward-compatible and convenience alias
ContextMemoryAgent = ContextResolutionAgent
