"""
Rolling memory for long conversations.

Follow-up questions are resolved against the last three exchanges, given in full. Older turns
are not dropped: they are folded into a short running summary of the conversation (facts,
figures, names, documents and decisions the user may come back to), stored with the chat and
given to the model ahead of the recent turns. The full conversation stays stored and shown;
only what the model reads is compressed. Each chat has its own memory; chats never share it.

The summary is brought up to date after each answer, in the background, with one call to the
fast model; if that is not possible, the earlier questions are kept verbatim instead.
"""
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("OmniDoc.ChatMemory")

RECENT_MESSAGES = 6        # the last three exchanges go to the model in full
SUMMARY_WORDS = 180
_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

PROMPT = """You keep the memory of a conversation between a user and OmniDoc, an assistant that answers from the user's documents.

Current memory (may be empty):
{memory}

Turns to add:
{turns}

Write the updated memory in at most {words} words: what the user asked about, the documents, companies, people, periods, figures and conclusions the answers gave, and anything the user may refer back to ("that invoice", "the second contract", "last year's figure"). Keep exact figures and names. No preamble."""


def history_for(messages: List[Dict[str, Any]], memory: Optional[str], memory_upto: int) -> List[Dict[str, str]]:
    """What the model reads: the summary of the older turns, any older turns it does not cover yet, and the recent ones."""
    turns = [{"role": m["role"], "content": m["content"]} for m in messages]
    older, recent = turns[:-RECENT_MESSAGES], turns[-RECENT_MESSAGES:]
    covered = min(memory_upto or 0, len(older))
    out: List[Dict[str, str]] = []
    if memory and covered:
        out.append({"role": "summary", "content": memory})
    # Turns that fell out of the recent window before the summary caught up: their questions, briefly.
    pending = [t for t in older[covered:] if t["role"] == "user"]
    if pending:
        out.append({"role": "summary", "content": "Earlier questions: " + " | ".join(t["content"][:200] for t in pending[-6:])})
    return out + recent


def _format(turns: List[Dict[str, Any]]) -> str:
    lines = []
    for t in turns:
        role = "User" if t["role"] == "user" else "OmniDoc"
        text = " ".join(str(t.get("content", "")).split())
        lines.append(f"{role}: {text[:400 if role == 'User' else 900]}")
    return "\n".join(lines)


def update(chat_id: str, get_messages: Callable[[str], List[Dict[str, Any]]], get_chat: Callable[[str], Optional[Dict[str, Any]]],
           save: Callable[[str, str, int], None], summarize: Callable[[str], str]) -> bool:
    """Folds the turns that left the recent window into the chat's memory. Returns whether it changed."""
    with _locks_guard:
        lock = _locks.setdefault(chat_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return False  # an update for this chat is already running
    try:
        chat = get_chat(chat_id)
        if not chat:
            return False
        messages = get_messages(chat_id)
        older = messages[:-RECENT_MESSAGES]
        upto = chat.get("memory_upto") or 0
        if len(older) <= upto:
            return False
        new = older[upto:]
        memory = chat.get("memory") or ""
        try:
            text = summarize(PROMPT.format(memory=memory or "(empty)", turns=_format(new), words=SUMMARY_WORDS)).strip()
        except Exception as e:
            logger.warning(f"Memory update for {chat_id} failed ({e}); keeping the earlier questions instead.")
            text = ""
        if not text:
            questions = [t["content"][:200] for t in new if t["role"] == "user"]
            text = (memory + " " if memory else "") + "Earlier questions: " + " | ".join(questions)
        save(chat_id, " ".join(text.split())[:2000], len(older))
        return True
    finally:
        lock.release()


def update_in_background(*args: Any) -> None:
    threading.Thread(target=update, args=args, name="chat-memory", daemon=True).start()
