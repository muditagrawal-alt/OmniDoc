"""
Context Resolution and Memory Agent for OmniDoc.
Resolves conversational anaphora, pronouns, and references across turns.
Maintains a compact structured conversation memory state.
"""
import re
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
import ollama

from core.state import ConversationMemoryState, AgentWorkflowState

logger = logging.getLogger("OmniDoc.ContextMemoryAgent")

CONTEXT_RESOLUTION_PROMPT = """You are the Context Resolution & Conversational Memory Agent of OmniDoc.
Your job is to resolve conversational pronouns and anaphoric references in the LATEST USER QUERY using the CONVERSATION HISTORY and ACTIVE CONTEXT.

Pronouns and references to resolve include:
- "it", "they", "them", "their"
- "this company", "that report", "the previous document"
- "same period", "that year", "then"
- "the above result", "the second one", "both of them"

Rules:
1. If the latest user query contains a reference to prior context (e.g. "plot it", "what about their revenue?"), rewrite it into a self-contained, fully-qualified query.
2. If the query is ALREADY self-contained, keep it unchanged.
3. Update active entities, time range, and topic.
4. Output ONLY valid JSON matching this schema:
{{
    "resolved_query": "fully qualified self-contained query",
    "active_entities": ["entity1", "entity2"],
    "active_time_range": "e.g. 2020-2024 or null",
    "active_topic": "e.g. Revenue Analysis or null",
    "references_resolved": ["it -> Tesla revenue", "they -> Ford and GM"]
}}

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

    def resolve_context(
        self,
        current_query: str,
        conversation_history: List[Dict[str, str]],
        memory_state: Optional[ConversationMemoryState] = None
    ) -> Tuple[str, ConversationMemoryState]:
        """
        Resolves references in the current query and updates structured memory.
        """
        if not conversation_history and (not memory_state or not memory_state.active_entities):
            # First turn: query is already self-contained
            initial_state = memory_state or ConversationMemoryState(
                previous_queries=[current_query]
            )
            return current_query, initial_state

        history_text = ""
        for turn in conversation_history[-4:]:  # Last 4 turns
            role = turn.get("role", "user").capitalize()
            content = turn.get("content", "")[:300]
            history_text += f"{role}: {content}\n"

        mem_dict = memory_state.model_dump() if memory_state else {}
        prompt = CONTEXT_RESOLUTION_PROMPT.format(
            active_memory=json.dumps(mem_dict, indent=2),
            history=history_text or "None",
            query=current_query
        )

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "num_predict": 512},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            resolved = parsed.get("resolved_query", current_query)
            
            # Update memory state
            updated_state = memory_state or ConversationMemoryState()
            new_entities = parsed.get("active_entities", [])
            if new_entities:
                updated_state.active_entities = list(set(updated_state.active_entities + new_entities))[:10]
            if parsed.get("active_time_range"):
                updated_state.active_time_range = parsed["active_time_range"]
            if parsed.get("active_topic"):
                updated_state.active_topic = parsed["active_topic"]
            
            updated_state.previous_queries.append(current_query)

            logger.info(f"Context Resolution: '{current_query}' -> '{resolved}'")
            return resolved, updated_state

        except Exception as e:
            logger.warning(f"Context resolution fallback triggered ({e}).")
            fallback_state = memory_state or ConversationMemoryState()
            fallback_state.previous_queries.append(current_query)
            return current_query, fallback_state


    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """LangGraph node execution wrapper."""
        query = state.get("user_query", "")
        history = state.get("conversation_history", [])
        mem_state = state.get("memory_state")
        resolved, updated_mem = self.resolve_context(query, history, mem_state)
        return {
            "user_query": resolved,
            "memory_state": updated_mem
        }


# Backward-compatible and convenience alias
ContextMemoryAgent = ContextResolutionAgent

