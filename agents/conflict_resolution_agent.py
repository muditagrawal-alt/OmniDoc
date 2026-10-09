"""
Conflict Resolution Agent for OmniDoc.
Audits candidate evidence for factual or numerical discrepancies across sources,
weighs reporting dates and document authority, and preserves uncertainty when necessary.

Each reported conflict must quote both contradicting statements; quotes are checked against
the evidence text and records whose quotes or evidence references cannot be verified are
dropped. Output records follow core.state.ConflictRecord (model_dump), plus the short
evidence keys and quotes used for the audit.
"""
import re
import time
import logging
from typing import Dict, Any, List, Optional, Tuple

from core.state import AgentWorkflowState, ConflictRecord, EvidencePackage, EvidenceItem
from agents.llm_utils import chat_json, as_list, trace

logger = logging.getLogger("OmniDoc.ConflictResolution")

MAX_ITEMS = 8
MAX_RECORDS = 3

CONFLICT_PROMPT = """You are the Conflict Resolution Auditor of OmniDoc.
Examine the evidence items and report only GENUINE contradictions: two items that make incompatible claims about the same fact or quantity, for the same entity and the same time period.
Different metrics, different years, different scopes, or complementary details are NOT conflicts. When in doubt, report no conflict.

For each genuine contradiction:
- quote the exact contradicting words from each item (copy them verbatim),
- decide whether one source is more authoritative (e.g. audited vs. preliminary, newer vs. older); if not resolvable, keep the uncertainty.

Return JSON only:
{{"conflicts": [{{"conflicting_claim": "what is disputed", "evidence_a": "E1", "quote_a": "verbatim words from E1", "evidence_b": "E2", "quote_b": "verbatim words from E2", "resolution_status": "resolved" or "unresolved_uncertainty", "preferred": "E1" or "E2" or null, "rationale": "why", "confidence": 0.0-1.0}}]}}
If there is no genuine contradiction return {{"conflicts": []}}.

EVIDENCE ITEMS:
{evidence_text}

USER QUERY:
{query}
"""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9.%$]+", " ", (text or "").lower()).strip()


def _quote_in(quote: str, content: str) -> bool:
    """Verbatim-ish check: the normalised quote (or most of its words) occurs in the content."""
    q, c = _norm(quote), _norm(content)
    if not q:
        return False
    if q in c:
        return True
    words = [w for w in q.split() if len(w) > 2]
    return bool(words) and sum(1 for w in words if w in c) / len(words) >= 0.8


_STOP = {"the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "which", "have", "has", "will",
         "would", "their", "they", "about", "into", "than", "more", "also", "such", "been", "its", "per"}


def numeric_facts(text: str) -> List[Tuple[frozenset, str, float]]:
    """(content words around a figure in its sentence, its unit, the figure) for each figure in a text."""
    facts = []
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        tokens = re.findall(r"[A-Za-z]{3,}|\d[\d,]*(?:\.\d+)?%?", sentence)
        for i, tok in enumerate(tokens):
            if not tok[0].isdigit():
                continue
            try:
                value = float(tok.rstrip("%").replace(",", ""))
            except ValueError:
                continue
            if 1800 <= value <= 2100 and "." not in tok and "," not in tok:
                continue  # years are dates, not quantities
            nxt = tokens[i + 1].lower() if i + 1 < len(tokens) and not tokens[i + 1][0].isdigit() else ""
            unit = "percent" if tok.endswith("%") or nxt in ("percent", "per") else nxt
            window = tokens[max(0, i - 3):i] + tokens[i + 1:i + 3]
            words = frozenset(w.lower() for w in window if not w[0].isdigit() and w.lower() not in _STOP)
            if len(words) >= 2:
                facts.append((words, unit, value))
    return facts


def _same_quantity(a: Tuple[frozenset, str, float], b: Tuple[frozenset, str, float]) -> bool:
    (words_a, unit_a, _), (words_b, unit_b, _) = a, b
    if unit_a and unit_b and unit_a != unit_b:
        return False
    return len(words_a & words_b) >= 2


def suspected_conflicts(items: List[EvidenceItem]) -> int:
    """
    Figures from different documents that describe the same thing (at least two of the
    words right around them match) but differ by more than rounding. Only when there are
    some is the model asked to audit the evidence, which saves a call on almost every
    question.
    """
    by_source: Dict[str, List[Tuple[frozenset, str, float]]] = {}
    for it in items:
        by_source.setdefault(_source_key(it), []).extend(numeric_facts(it.content or ""))
    sources = list(by_source.values())
    count = 0
    for i, facts_a in enumerate(sources):
        values_a = {f[2] for f in facts_a}
        for facts_b in sources[i + 1:]:
            values_b = {f[2] for f in facts_b}
            for fa in facts_a:
                for fb in facts_b:
                    va, vb = fa[2], fb[2]
                    if _same_quantity(fa, fb) and abs(va - vb) > 0.01 * max(abs(va), abs(vb), 1e-9) \
                            and va not in values_b and vb not in values_a:
                        count += 1
    return count


def _source_key(item: EvidenceItem) -> str:
    prov = item.provenance or {}
    return str(prov.get("doc_id") or item.evidence_id)


class ConflictResolutionAgent:
    """Reconciles contradictory claims across multi-document evidence."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def _record(self, raw: Dict[str, Any], keyed: Dict[str, EvidenceItem]) -> Optional[Dict[str, Any]]:
        ka = str(raw.get("evidence_a") or raw.get("evidence_a_id") or "").strip().upper()
        kb = str(raw.get("evidence_b") or raw.get("evidence_b_id") or "").strip().upper()
        if ka not in keyed or kb not in keyed or ka == kb:
            return None
        item_a, item_b = keyed[ka], keyed[kb]
        quote_a, quote_b = str(raw.get("quote_a") or ""), str(raw.get("quote_b") or "")
        if not (_quote_in(quote_a, item_a.content) and _quote_in(quote_b, item_b.content)):
            return None
        status = raw.get("resolution_status")
        status = status if status in ("resolved", "unresolved_uncertainty") else "unresolved_uncertainty"
        preferred_key = str(raw.get("preferred") or raw.get("preferred_evidence_id") or "").strip().upper()
        preferred = keyed[preferred_key].evidence_id if preferred_key in (ka, kb) else None
        if status == "resolved" and preferred is None:
            status = "unresolved_uncertainty"
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        record = ConflictRecord(
            conflicting_claim=str(raw.get("conflicting_claim") or "Contradictory statements")[:300],
            evidence_a=item_a,
            evidence_b=item_b,
            resolution_status=status,
            preferred_evidence_id=preferred,
            rationale=str(raw.get("rationale") or "")[:600],
            confidence=confidence,
        ).model_dump()
        record.update({"evidence_a_id": item_a.evidence_id, "evidence_b_id": item_b.evidence_id,
                       "quote_a": quote_a[:300], "quote_b": quote_b[:300]})
        return record

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Audits evidence package for discrepancies before synthesis.
        """
        started = time.perf_counter()
        query = state.get("user_query", "")
        ev_package: Optional[EvidencePackage] = state.get("evidence_package")
        items = [it for it in (ev_package.items if ev_package else []) if it.source_type != "kg_triple"][:MAX_ITEMS]
        # Contradictions are audited across sources (documents); evidence from a single
        # document is not audited, which also saves an LLM call on the common single-doc case.
        if len(items) < 2:
            return {"conflicts": [], "agent_traces": [trace("conflict_resolution", "skipped", "Fewer than two evidence items.", started)]}
        if len({_source_key(it) for it in items}) < 2:
            return {"conflicts": [], "agent_traces": [trace("conflict_resolution", "skipped", "All evidence comes from one document.", started)]}

        suspects = suspected_conflicts(items)
        if not suspects:
            return {"conflicts": [], "agent_traces": [trace("conflict_resolution", "skipped",
                                                             "No differing figures about the same thing across documents.", started)]}

        keyed = {f"E{i}": it for i, it in enumerate(items, 1)}
        ev_text = "\n\n".join(f"[{k}] ({it.provenance.get('doc_id', '') if it.provenance else ''}): {it.content[:1200]}"
                              for k, it in keyed.items())
        try:
            parsed = chat_json(
                self.model_name,
                CONFLICT_PROMPT.format(evidence_text=ev_text, query=query),
                num_predict=700,
            )
        except Exception as e:
            logger.warning(f"Conflict audit unavailable ({e}).")
            return {"conflicts": [], "agent_traces": [trace("conflict_resolution", "failed", str(e)[:200], started)]}

        raw_records = parsed.get("conflicts", parsed.get("records", [])) if isinstance(parsed, dict) else parsed
        records, rejected = [], 0
        for raw in as_list(raw_records)[:MAX_RECORDS * 2]:
            rec = self._record(raw, keyed) if isinstance(raw, dict) else None
            if rec:
                records.append(rec)
            else:
                rejected += 1
        records = records[:MAX_RECORDS]
        detail = f"{len(records)} verified conflict(s)" + (f", {rejected} unverifiable claim(s) discarded" if rejected else "")
        logger.info(f"ConflictResolution: {detail}")
        return {"conflicts": records, "agent_traces": [trace("conflict_resolution", "completed", detail, started)]}
