"""
Synthesis and Citation Agent Node for LangGraph.
Combines evidence from Graph, Vector Chunks, Math computations, Visual artifacts,
and Conflict audits into an authoritative, grounded answer with strict inline citations.
"""
import json
import logging
from typing import Dict, Any, List, Optional
import ollama

from core.state import AgentWorkflowState, EvidencePackage, MathExecutionResult, VisualizationArtifact

logger = logging.getLogger("OmniDoc.SynthesisAgent")

SYNTHESIS_PROMPT = """You are the Lead Synthesis and Fact-Verification Agent for OmniDoc.

Your mission is to synthesize a clear, comprehensive, and factual answer to the USER QUERY strictly using the PROVIDED MULTI-SOURCE EVIDENCE.

EVIDENCE:
{evidence}

USER QUERY:
{query}

STRICT GROUNDING & CITATION RULES:
1. Answer ONLY using the facts present in the evidence. Do NOT extrapolate or assume external facts.
2. If the answer is NOT present in the evidence, reply with:
   "Not found in provided sources. The uploaded documents do not contain sufficient evidence to answer this question."
3. Every factual statement MUST cite its source using inline brackets:
   - "[Chunk: <chunk_id>]" for passage text
   - "[Entity: <entity_name>]" for knowledge graph facts
   - "[Figure: <id>]" for visual analyses
   - "[Calculation: <task>]" for mathematical computations
   - "[Conflict Note]" when discussing resolved or unresolved discrepancies
4. Mathematical Precision: If exact mathematical computations are provided in EVIDENCE, use the EXACT numbers calculated. Include the formula in standard LaTeX notation ($...$ or $$...$$) and detail the calculation steps.
5. Visual Artifacts: If interactive charts were generated, guide the user's attention to the chart (e.g., "As visualized in the interactive chart below: ...") and summarize the core trend.
6. Transparency on Discrepancies: If conflicting sources exist in the evidence, explain the differences transparently (e.g., chronological updates, GAAP vs Non-GAAP, different business units).
7. Structure the response logically with clear Markdown headings, bullet points, or comparison tables where appropriate.
"""


class SynthesisAgent:
    """Combines multi-modal, mathematical, and multi-hop evidence into a cited answer."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def synthesize(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Synthesizes a cited draft response from the accumulated state.
        """
        # Resolve query representation
        semantic_q = state.get("semantic_query")
        raw_query = state.get("user_query", "")
        effective_query = semantic_q.raw_query if semantic_q and semantic_q.raw_query else raw_query

        chunks = state.get("chunk_context", [])
        graph_data = state.get("graph_context", [])
        visuals = state.get("visual_context", [])
        web = state.get("web_context", [])
        math_results = state.get("math_results", [])
        visual_artifacts = state.get("visual_artifacts", [])
        conflicts = state.get("conflicts", [])
        evidence_pkg: Optional[EvidencePackage] = state.get("evidence_package")

        evidence_blocks = []

        # 1. Evidence Package (Ranked & Deduplicated Evidence)
        if evidence_pkg and evidence_pkg.items:
            evidence_blocks.append("=== VERIFIED EVIDENCE PACKAGE ===")
            for item in evidence_pkg.items:
                ev_id = item.evidence_id
                stype = item.source_type
                prov = item.provenance or {}
                prov_str = f"Doc: {prov.get('doc_id', '')}, Pg: {prov.get('page_no', 1)}" if prov else ""
                evidence_blocks.append(f"[{stype}: {item.source_id}] ({prov_str}):\n{item.content}")
        else:
            # Fallback to raw chunks if evidence package wasn't built
            if chunks:
                evidence_blocks.append("=== RETRIEVED DOCUMENT CHUNKS ===")
                for ch in chunks:
                    cid = ch.get("chunk_id", "Unknown")
                    sec = ch.get("section_title", "General")
                    pg = ch.get("page_number", 1)
                    text = ch.get("text", "")
                    if text:
                        evidence_blocks.append(f"[Chunk: {cid}] (Section: {sec}, Page: {pg}):\n{text}")

        # 2. Knowledge Graph Triples
        if graph_data:
            evidence_blocks.append("\n=== KNOWLEDGE GRAPH RELATIONSHIPS ===")
            for g in graph_data:
                for edge in g.get("edges", []):
                    src = edge.get("source_name", edge.get("source"))
                    tgt = edge.get("target_name", edge.get("target"))
                    rel = edge.get("relation")
                    desc = edge.get("description", "")
                    evidence_blocks.append(f"[Entity: {src}] -[{rel}]-> [Entity: {tgt}] ({desc})")

        # 3. Verified Mathematical Computations
        if math_results:
            evidence_blocks.append("\n=== VERIFIED MATHEMATICAL COMPUTATIONS (SANDBOXED PYTHON) ===")
            for mr in math_results:
                task = mr.get("task", "Calculation")
                formula = mr.get("formula", "")
                result = mr.get("exact_result")
                units = mr.get("units", "")
                inputs = mr.get("inputs", {})
                evidence_blocks.append(
                    f"[Calculation: {task}]\n"
                    f"- Inputs: {json.dumps(inputs)}\n"
                    f"- Formula: {formula}\n"
                    f"- Computed Result: {result} {units or ''}\n"
                    f"- Assumptions: {', '.join(mr.get('assumptions', []))}"
                )

        # 4. Interactive Visual Artifacts
        if visual_artifacts:
            evidence_blocks.append("\n=== GENERATED INTERACTIVE VISUALIZATIONS ===")
            for va in visual_artifacts:
                ctype = va.get("chart_type", "chart")
                title = va.get("title", "Visualization")
                caption = va.get("caption", "")
                data_summary = va.get("underlying_data", [])
                evidence_blocks.append(
                    f"[Visualization: {title} ({ctype})]\n"
                    f"- Key Insight: {caption}\n"
                    f"- Plotted Data: {json.dumps(data_summary[:6])}"
                )

        # 5. Multimodal / Visual Findings
        if visuals:
            evidence_blocks.append("\n=== MULTIMODAL / VISUAL FINDINGS ===")
            for v in visuals:
                if "analysis" in v:
                    evidence_blocks.append(f"[Visual Analysis ({v.get('image_path', 'Diagram')}]: {v['analysis']}")

        # 6. Discrepancy & Conflict Audit
        if conflicts:
            evidence_blocks.append("\n=== EVIDENCE DISCREPANCY & CONFLICT AUDIT ===")
            for c in conflicts:
                evidence_blocks.append(
                    f"[Conflict Note: {c.get('conflicting_claim', 'Claim Discrepancy')}]\n"
                    f"- Status: {c.get('resolution_status', 'unresolved')}\n"
                    f"- Resolution Rationale: {c.get('rationale', '')}\n"
                    f"- Preferred Source: {c.get('preferred_evidence_id', 'N/A')}"
                )

        # 7. Real-Time Web Results
        if web:
            evidence_blocks.append("\n=== REAL-TIME EXTERNAL WEB SOURCES ===")
            for w in web:
                evidence_blocks.append(f"[Web: {w.get('title')}]: {w.get('snippet')} (URL: {w.get('url')})")

        combined_evidence = "\n\n".join(evidence_blocks)

        if not combined_evidence.strip():
            logger.warning("No evidence gathered. Emitting standard boundary refusal.")
            return {
                "draft_response": "Not found in provided sources. No relevant document context could be retrieved."
            }

        try:
            prompt = SYNTHESIS_PROMPT.format(evidence=combined_evidence[:18000], query=effective_query)
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.2, "num_predict": 1500},
                stream=False
            )
            draft = response["message"]["content"].strip()
            return {"draft_response": draft}

        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return {
                "draft_response": f"Error during synthesis: {str(e)}",
                "errors": [str(e)]
            }

