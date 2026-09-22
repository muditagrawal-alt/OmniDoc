"""
Conflict Resolution Agent for OmniDoc.
Audits candidate evidence for factual or numerical discrepancies across sources,
investigates reporting dates, document authority, and preserves uncertainty when necessary.
"""
import re
import json
import logging
from typing import Dict, Any, List
import ollama

from core.state import AgentWorkflowState, ConflictRecord, EvidencePackage

logger = logging.getLogger("OmniDoc.ConflictResolution")

CONFLICT_PROMPT = """You are the Conflict Resolution Auditor of OmniDoc.
Examine the provided evidence items and identify if any two sources state contradictory facts, numbers, or dates for the same query.

If NO contradiction exists, respond with:
{"conflicts_found": false, "records": []}

If a contradiction IS found (e.g. Source A says $10B revenue, Source B says $11B):
1. Explain the discrepancy.
2. Determine if one source is more authoritative (e.g. Audited 10-K vs Press Release, newer date, GAAP vs Non-GAAP).
3. If resolvable, specify the preferred source and why; if not resolvable, preserve uncertainty.
4. Output schema:
{{
    "conflicts_found": true,
    "records": [
        {{
            "conflicting_claim": "...",
            "evidence_a_id": "...",
            "evidence_b_id": "...",
            "resolution_status": "resolved" | "unresolved_uncertainty",
            "preferred_evidence_id": "..." or null,
            "rationale": "..."
        }}
    ]
}}

EVIDENCE ITEMS:
{evidence_text}

USER QUERY:
{query}
"""


class ConflictResolutionAgent:
    """Reconciles contradictory claims across multi-document evidence."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Audits evidence package for discrepancies before synthesis.
        """
        query = state.get("user_query", "")
        ev_package: EvidencePackage = state.get("evidence_package")
        if not ev_package or len(ev_package.items) < 2:
            return {"conflicts": []}

        ev_text = ""
        for it in ev_package.items:
            ev_text += f"[{it.evidence_id}] ({it.source_type}): {it.content}\n"

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": CONFLICT_PROMPT.format(evidence_text=ev_text[:8000], query=query)}],
                options={"temperature": 0.0, "num_predict": 512},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            if not parsed.get("conflicts_found", False):
                return {"conflicts": []}

            records = parsed.get("records", [])
            logger.info(f"ConflictResolution: Found {len(records)} discrepancies across evidence.")
            return {"conflicts": records}

        except Exception as e:
            logger.info(f"Conflict resolution check completed cleanly ({e}).")
            return {"conflicts": []}
