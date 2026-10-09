"""
Synthesis and Citation Agent Node for LangGraph.
Combines evidence from vector chunks, graph triples, verified calculations, figure analyses,
conflict audits and web results into one numbered evidence list, and writes a grounded
answer that cites that list inline as [1], [2], ... The same list is returned as ``sources``.
"""
import time
import logging
from typing import Dict, Any, List

from core.state import AgentWorkflowState
from core import streaming
from agents.llm_utils import chat, chat_stream, trace
from agents.citations import (
    sources_from_state,
    public_sources,
    format_evidence_block,
    normalize_citations,
    cited_numbers,
)

logger = logging.getLogger("OmniDoc.SynthesisAgent")

REFUSAL_SENTENCE = "The current document collection does not contain verifiable records regarding this topic."

SYNTHESIS_SYSTEM_PROMPT = """You are the Senior Research Analyst and Synthesis Specialist for OmniDoc.
Your mission is to write an authoritative, direct answer to the user's question based strictly on the NUMBERED EVIDENCE supplied in the user message.

CITATION RULES (mandatory):
- After every sentence or bullet that uses information from the evidence, cite the supporting evidence item(s) with their bracketed numbers, e.g. "... by 2030 [2]." or "... [1][3]."
- Use only the numbers 1 to {n}. Never cite a number that is not in the list, never invent sources, and do not add a "Sources" or "References" list at the end (the interface shows the sources).

EDITORIAL & PRESENTATION GUIDELINES:
1. Voice & Tone: Write in a natural, precise, professional tone. Do NOT start with boilerplate such as "Based on the provided text...", "In the documents provided..." or "According to the evidence...". Start with the core insight.
2. Structure:
   - Begin with a concise summary sentence or paragraph that directly answers the question.
   - For multi-part or detailed answers, use clean markdown headings (## and ###) for distinct sections; short factual answers need no headings.
   - Present details in fluent prose or cleanly spaced bullet points with bold lead-ins. Never output raw unformatted dumps of the evidence.
3. Strict Grounding:
   - Use ONLY facts from the evidence. Do not add outside knowledge, estimates or examples that are not in the evidence. If the required information is genuinely missing, clearly state:
     "{refusal}"
   - If only part of the question is answered by the evidence, answer that part and say plainly what is not covered.
   - If a conflict note is listed, mention the disagreement instead of silently picking one value.
4. Mathematical Precision:
   - When financial or mathematical values are present, use the exact figures from the evidence; use verified calculation results as given and cite them.
   - Format formulas cleanly in LaTeX using single $ for inline (e.g., $E = mc^2$) or double $$ for display equations.
"""

REFLECTION_SECTION = """VERIFIER FEEDBACK - REVISION REQUIRED:
An independent fact-checker compared your previous draft with the numbered evidence and flagged claims that the evidence does not support:
{feedback}

Rewrite the answer: remove each flagged claim or explicitly qualify it as not established by the documents, keep only statements supported by the numbered evidence, and cite only those numbers.

PREVIOUS DRAFT:
{previous}
"""


class SynthesisAgent:
    """Combines multi-modal, mathematical, and multi-hop evidence into a cited answer."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    @staticmethod
    def _timeline_block(state: AgentWorkflowState, sources: List[Dict[str, Any]]) -> List[str]:
        """Dated statements in order (temporal reasoning), each with the number of the passage it came from."""
        by_chunk = {s.get("chunk_id"): s["n"] for s in sources if s.get("chunk_id")}
        lines = []
        for e in state.get("timeline") or []:
            n = by_chunk.get(e.get("chunk_id"))
            if n:
                lines.append(f"- {e['written']} ({e['date']}): {e['text'][:220]} [{n}]")
        return ["", "DATED STATEMENTS FROM THE EVIDENCE, IN ORDER:"] + lines if lines else []

    def _build_user_prompt(self, state: AgentWorkflowState, query: str, sources: List[Dict[str, Any]]) -> str:
        parts = [f"NUMBERED EVIDENCE ({len(sources)} items):", format_evidence_block(sources), "", "USER QUESTION:", query]
        semantic_q = state.get("semantic_query")
        subs = [q for q in (getattr(semantic_q, "sub_questions", None) or []) if isinstance(q, str) and q.strip()]
        if len(subs) > 1:
            parts += ["", "The question has these parts; answer each one (or say which the evidence does not cover):"]
            parts += [f"{i}. {q}" for i, q in enumerate(subs[:5], 1)]
        parts += self._timeline_block(state, sources)

        charts = [va for va in (state.get("visual_artifacts") or []) if isinstance(va, dict) and va.get("title")]
        if charts:
            titles = "; ".join(str(va["title"]) for va in charts[:3])
            parts += ["", f"NOTE: The interface displays chart(s) built from this evidence ({titles}). "
                          "You may refer to the chart, but cite the evidence numbers for any figure you state."]

        language = state.get("answer_language") or getattr(semantic_q, "language", "en") or "en"
        if language.lower() not in ("en", "eng", "english"):
            from agents.multilingual_agent import LANGUAGE_NAMES
            parts += ["", f"Write the whole answer in {LANGUAGE_NAMES.get(language, language)}, keeping numbers, formulas, "
                          "names and the [n] citations exactly as they are."]

        feedback = state.get("reflection_feedback")
        if feedback:
            previous = (state.get("draft_response") or "").strip()[:4000] or "(empty)"
            parts += ["", REFLECTION_SECTION.format(feedback=str(feedback).strip()[:1500], previous=previous)]

        parts += ["", f"Answer now, citing evidence as [n] with n between 1 and {len(sources)}."]
        return "\n".join(parts)

    def synthesize(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Synthesizes a cited draft response and returns it with the numbered ``sources`` list.
        """
        started = time.perf_counter()
        semantic_q = state.get("semantic_query")
        raw_query = state.get("user_query", "")
        effective_query = (getattr(semantic_q, "resolved_query", None) or getattr(semantic_q, "raw_query", None)
                           or raw_query)

        sources = sources_from_state(state)
        public = public_sources(sources)

        if not sources:
            logger.warning("No evidence gathered. Emitting boundary refusal.")
            return {
                "draft_response": REFUSAL_SENTENCE,
                "sources": [],
                "agent_traces": [trace("synthesis_agent", "completed", "No evidence retrieved; refusal emitted.", started)],
            }

        system = SYNTHESIS_SYSTEM_PROMPT.format(n=len(sources), refusal=REFUSAL_SENTENCE)
        user = self._build_user_prompt(state, effective_query, sources)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        run_id = state.get("run_id") or ""

        try:
            if streaming.listening(run_id):
                # Stream the draft to the client while it is written; a revision replaces it.
                streaming.emit(run_id, "reset" if state.get("reflection_feedback") else "sources", public)
                raw = chat_stream(self.model_name, messages,
                                  lambda piece: streaming.emit(run_id, "delta", piece),
                                  on_reset=lambda: streaming.emit(run_id, "reset", public),
                                  temperature=0.2, num_predict=1500)
            else:
                raw = chat(self.model_name, messages, temperature=0.2, num_predict=1500)
            draft = normalize_citations(raw, len(sources))
            if not draft:
                raise ValueError("model returned an empty answer")
            cited = cited_numbers(draft)
            detail = f"{len(sources)} sources, cited {cited}"
            if state.get("reflection_feedback"):
                detail = "Revised after verifier feedback; " + detail
            return {
                "draft_response": draft,
                "sources": public,
                "agent_traces": [trace("synthesis_agent", "completed", detail, started)],
            }
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return {
                "draft_response": f"Error during synthesis: {str(e)}",
                "sources": public,
                "errors": [f"Synthesis error: {e}"],
                "agent_traces": [trace("synthesis_agent", "failed", str(e)[:200], started)],
            }
