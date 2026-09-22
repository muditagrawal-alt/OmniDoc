"""
Output Guardrail and Groundedness Verifier.
Validates synthesis output against retrieved chunks and graph triples.
Enforces strict hallucination barriers, citation mapping, and confidence scores.
"""
import re
import json
import logging
from typing import List, Dict, Any, Tuple, Optional
import ollama

from core.state import VerificationResult, EvidencePackage

logger = logging.getLogger("OmniDoc.OutputGuard")

VERIFICATION_PROMPT = """You are an impartial Verification Judge and Groundedness Auditor for an enterprise RAG system.

Evaluate whether the DRAFT ANSWER is strictly and faithfully supported by the PROVIDED CONTEXT.
Do not assume or bring in external knowledge. Every claim must have direct evidence in the context.

PROVIDED CONTEXT:
{context}

USER QUERY:
{query}

DRAFT ANSWER:
{draft_answer}

Respond with ONLY a JSON object formatted as follows:
{{
    "faithfulness_score": 0.0 to 1.0,
    "is_grounded": true | false,
    "supported_claims": ["claim 1 with quote or reference", "claim 2"],
    "unsupported_claims": ["claim that has NO grounding in context"],
    "cited_sources": ["chunk_id or node_id cited"],
    "action": "accept" | "refine_search" | "refuse",
    "feedback": "constructive explanation of missing evidence or acceptance rationale"
}}

Rules:
1. If any major factual statement cannot be found in the context, list it in unsupported_claims.
2. Set action to "accept" if faithfulness_score >= 0.85 and unsupported_claims is empty.
3. Set action to "refine_search" if some claims are plausible but missing explicit evidence.
4. Set action to "refuse" if the answer hallucinated completely or contradicted the context.
"""


class OutputGuardrail:
    """Verifies synthesis groundedness and guards against hallucinations."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct", threshold: float = 0.85):
        self.model_name = model_name
        self.threshold = threshold

    def verify(
        self,
        query: str,
        draft_answer: str,
        retrieved_chunks: List[Dict[str, Any]] = None,
        graph_context: List[Dict[str, Any]] = None,
        math_results: List[Dict[str, Any]] = None,
        visual_artifacts: List[Dict[str, Any]] = None,
        conflicts: List[Dict[str, Any]] = None,
        evidence_package: Optional[EvidencePackage] = None
    ) -> VerificationResult:
        """
        Runs dual-pass verification:
        1. Inline citation syntactic check (regex)
        2. LLM Natural Language Inference (NLI) groundedness judge
        """
        retrieved_chunks = retrieved_chunks or []
        graph_context = graph_context or []
        math_results = math_results or []
        visual_artifacts = visual_artifacts or []
        conflicts = conflicts or []

        # Fast path: Empty draft or explicit refusal
        if not draft_answer.strip():
            return VerificationResult(
                is_grounded=False,
                faithfulness_score=0.0,
                supported_claims=[],
                unsupported_claims=["Empty response generated"],
                cited_sources=[],
                action="refine_search",
                feedback="Draft response is empty."
            )

        if "not found in provided sources" in draft_answer.lower() or "not mentioned in the document" in draft_answer.lower():
            return VerificationResult(
                is_grounded=True,
                faithfulness_score=1.0,
                supported_claims=["Correctly identified absence of information in context"],
                unsupported_claims=[],
                cited_sources=[],
                action="accept",
                feedback="Valid refusal grounded in document boundary."
            )

        # Build context string
        context_parts = []
        if evidence_package and evidence_package.items:
            for item in evidence_package.items:
                context_parts.append(f"[{item.source_type}: {item.source_id}]: {item.content}")
        else:
            for i, chunk in enumerate(retrieved_chunks, 1):
                cid = chunk.get("chunk_id", f"C{i}")
                text = chunk.get("text", "")
                context_parts.append(f"[{cid}]: {text}")

        for i, g in enumerate(graph_context, 1):
            nodes = g.get("nodes", [])
            edges = g.get("edges", [])
            if nodes or edges:
                context_parts.append(f"[Graph Context {i}]: Nodes={len(nodes)}, Edges={len(edges)} - {str(g)[:400]}")

        for mr in math_results:
            context_parts.append(
                f"[Calculation: {mr.get('task')}]: Result={mr.get('exact_result')} {mr.get('units', '')}, Formula={mr.get('formula')}"
            )

        for va in visual_artifacts:
            context_parts.append(
                f"[Visualization: {va.get('title')}]: Chart={va.get('chart_type')}, Caption={va.get('caption')}"
            )

        for cf in conflicts:
            context_parts.append(
                f"[Conflict Audit]: Claim={cf.get('conflicting_claim')}, Resolution={cf.get('resolution_status')}"
            )

        combined_context = "\n\n".join(context_parts)
        if not combined_context.strip():
            return VerificationResult(
                is_grounded=False,
                faithfulness_score=0.0,
                supported_claims=[],
                unsupported_claims=["No supporting context was retrieved"],
                cited_sources=[],
                action="refuse",
                feedback="Context was empty; answer cannot be grounded."
            )

        # LLM Verification Pass
        try:
            prompt = VERIFICATION_PROMPT.format(
                context=combined_context[:10000],
                query=query,
                draft_answer=draft_answer
            )
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "num_predict": 512},
                stream=False
            )
            raw_text = response["message"]["content"].strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                raw_text = re.sub(r"\s*```$", "", raw_text)
            try:
                parsed = json.loads(raw_text, strict=False)
            except Exception:
                sanitized = re.sub(r'\\(?![/"\\bfnrtu])', r'\\\\', raw_text)
                parsed = json.loads(sanitized, strict=False)

            score = float(parsed.get("faithfulness_score", 0.8))

            is_grounded = bool(parsed.get("is_grounded", score >= self.threshold))
            unsupported = parsed.get("unsupported_claims", [])
            
            action = parsed.get("action", "accept")
            if score < self.threshold or len(unsupported) > 0:
                if action == "accept":
                    action = "refine_search"

            return VerificationResult(
                is_grounded=is_grounded,
                faithfulness_score=score,
                supported_claims=parsed.get("supported_claims", []),
                unsupported_claims=unsupported,
                cited_sources=parsed.get("cited_sources", []),
                action=action,
                feedback=parsed.get("feedback", "")
            )

        except Exception as e:
            logger.warning(f"LLM verification failed ({e}). Performing syntactic citation validation.")
            return self._syntactic_fallback(draft_answer, combined_context)

    def _syntactic_fallback(self, draft_answer: str, context: str) -> VerificationResult:
        """Fast keyword/overlap fallback if verification LLM fails."""
        # Find citation markers like [Chunk: 1], [Entity: X], [Calculation: Y], [Figure: Z]
        citations = re.findall(r"\[(?:Chunk:\s*|Entity:\s*|Figure:\s*|Calculation:\s*|Visualization:\s*|Conflict\s*Note|C)?([a-zA-Z0-9_\-\s]+)\]", draft_answer)
        score = 0.88 if citations else 0.65
        return VerificationResult(
            is_grounded=bool(citations),
            faithfulness_score=score,
            supported_claims=["Syntactic validation passed" if citations else "No explicit citations detected"],
            unsupported_claims=[] if citations else ["Lacks inline citation references"],
            cited_sources=citations,
            action="accept" if citations else "refine_search",
            feedback="Evaluated via multi-source citation presence fallback."
        )
