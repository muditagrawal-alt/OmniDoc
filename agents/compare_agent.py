"""
Comparing two documents (versions of a contract, two reports, two offers).

The documents are split into sentences and aligned with a sequence matcher, so moved or
reworded sentences are paired by similarity rather than position. Each change is
"modified" (with a word-level diff and the figures that changed), "added" or "removed",
and carries the page and passage of each side so the viewer can show it. No model call;
an optional summary of the most important changes takes one.
"""
import re
import difflib
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agents.llm_utils import chat, extract_numbers

logger = logging.getLogger("OmniDoc.Compare")

_SENT = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z0-9(\"'“])|\n+")
MAX_SENTENCES = 4000
PAIR_SIMILARITY = 0.55

SUMMARY_PROMPT = """Two versions of a document were compared. Summarise what changed and why it matters, in 4 to 8 bullet points, most important first (money, dates, obligations, numbers, parties). Use only the changes listed. Refer to each change by its number like (C3).

DOCUMENT A: {a}
DOCUMENT B: {b}

CHANGES:
{changes}"""


def _key(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def sentences(chunks: Sequence[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in chunks:
        for s in _SENT.split(c.text or ""):
            s = s.strip()
            if len(s) >= 12:
                out.append({"text": s, "page": c.page_number, "chunk_id": c.chunk_id, "key": _key(s)})
            if len(out) >= MAX_SENTENCES:
                return out
    return out


def word_diff(a: str, b: str) -> List[Tuple[str, str]]:
    """[(op, text)] with op in "=", "-", "+" (words and the spaces after them)."""
    ta, tb = re.findall(r"\S+\s*", a), re.findall(r"\S+\s*", b)
    out: List[Tuple[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [t.strip() for t in ta], [t.strip() for t in tb], autojunk=False).get_opcodes():
        if op == "equal":
            out.append(("=", "".join(ta[i1:i2])))
        else:
            if i2 > i1:
                out.append(("-", "".join(ta[i1:i2])))
            if j2 > j1:
                out.append(("+", "".join(tb[j1:j2])))
    return out


def changed_figures(a: str, b: str) -> List[Dict[str, float]]:
    na, nb = extract_numbers(a), extract_numbers(b)
    removed = [x for x in na if x not in nb]
    added = [x for x in nb if x not in na]
    return [{"from": x, "to": y} for x, y in zip(removed, added)]


def _side(s: Dict[str, Any]) -> Dict[str, Any]:
    return {"text": s["text"], "page": s["page"], "chunk_id": s["chunk_id"]}


def _pair_block(a_block: List[Dict[str, Any]], b_block: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pairs the sentences of a replaced block by similarity; the rest are removed or added."""
    changes: List[Dict[str, Any]] = []
    used = set()
    for sa in a_block:
        best_j, best = None, 0.0
        for j, sb in enumerate(b_block):
            if j in used:
                continue
            ratio = difflib.SequenceMatcher(None, sa["key"], sb["key"], autojunk=False).ratio()
            if ratio > best:
                best_j, best = j, ratio
        if best_j is not None and best >= PAIR_SIMILARITY:
            used.add(best_j)
            sb = b_block[best_j]
            changes.append({"kind": "modified", "a": _side(sa), "b": _side(sb), "similarity": round(best, 3),
                            "diff": word_diff(sa["text"], sb["text"]), "figures": changed_figures(sa["text"], sb["text"])})
        else:
            changes.append({"kind": "removed", "a": _side(sa), "b": None})
    for j, sb in enumerate(b_block):
        if j not in used:
            changes.append({"kind": "added", "a": None, "b": _side(sb)})
    return changes


def compare(chunks_a: Sequence[Any], chunks_b: Sequence[Any]) -> Dict[str, Any]:
    sa, sb = sentences(chunks_a), sentences(chunks_b)
    matcher = difflib.SequenceMatcher(None, [s["key"] for s in sa], [s["key"] for s in sb], autojunk=False)
    changes: List[Dict[str, Any]] = []
    same = 0
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            same += i2 - i1
        elif op == "replace":
            changes.extend(_pair_block(sa[i1:i2], sb[j1:j2]))
        elif op == "delete":
            changes.extend({"kind": "removed", "a": _side(s), "b": None} for s in sa[i1:i2])
        elif op == "insert":
            changes.extend({"kind": "added", "a": None, "b": _side(s)} for s in sb[j1:j2])
    # Sentences that only moved count as unchanged.
    removed = {c["a"]["text"].lower(): k for k, c in enumerate(changes) if c["kind"] == "removed"}
    moved = set()
    for k, c in enumerate(changes):
        if c["kind"] == "added" and c["b"]["text"].lower() in removed:
            moved.update({k, removed[c["b"]["text"].lower()]})
    changes = [c for k, c in enumerate(changes) if k not in moved]
    for i, c in enumerate(changes, 1):
        c["id"] = f"C{i}"
    stats = {
        "unchanged": same + len(moved) // 2,
        "modified": sum(c["kind"] == "modified" for c in changes),
        "added": sum(c["kind"] == "added" for c in changes),
        "removed": sum(c["kind"] == "removed" for c in changes),
        "figures": sum(1 for c in changes if c.get("figures")),
        "sentences_a": len(sa), "sentences_b": len(sb),
        "similarity": round(matcher.ratio(), 3),
    }
    return {"changes": changes, "stats": stats}


def _change_line(c: Dict[str, Any]) -> str:
    if c["kind"] == "modified":
        return f"({c['id']}) changed: \"{c['a']['text'][:300]}\" -> \"{c['b']['text'][:300]}\""
    if c["kind"] == "added":
        return f"({c['id']}) added: \"{c['b']['text'][:300]}\""
    return f"({c['id']}) removed: \"{c['a']['text'][:300]}\""


def summarize(model: str, title_a: str, title_b: str, changes: List[Dict[str, Any]], limit: int = 40) -> str:
    """One model call: the most important changes, figures and modifications first."""
    ranked = sorted(changes, key=lambda c: (0 if c.get("figures") else 1 if c["kind"] == "modified" else 2))
    listing = "\n".join(_change_line(c) for c in ranked[:limit])
    if not listing:
        return "The documents say the same thing."
    return chat(model, [{"role": "user", "content": SUMMARY_PROMPT.format(a=title_a, b=title_b, changes=listing[:14000])}],
                temperature=0.1, num_predict=600)
