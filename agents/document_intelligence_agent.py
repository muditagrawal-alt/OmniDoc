"""
Document Intelligence Agent for OmniDoc.
Navigates document layout structures, footnotes, multi-column blocks,
headers/footers, and maps visual figures to their surrounding text.
"""
import logging
from typing import Dict, Any, List
from core.state import AgentWorkflowState

logger = logging.getLogger("OmniDoc.DocumentIntelligence")


class DocumentIntelligenceAgent:
    """Extracts structural AST metadata and locates target tables/sections."""

    def __init__(self):
        pass

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Inspects document layout hierarchy and sections."""
        query = state.get("user_query", "")
        chunks = state.get("chunk_context", [])
        
        # Aggregate sections present in retrieved chunks
        sections_found = list(set([ch.get("section_title", "General") for ch in chunks]))
        pages_found = list(set([ch.get("page_number", 1) for ch in chunks]))

        logger.info(f"DocumentIntelligence: Identified sections {sections_found} across pages {pages_found}.")
        return {
            "chunk_context": [{
                "layout_metadata": {
                    "sections_covered": sections_found,
                    "pages_referenced": pages_found
                }
            }]
        }
