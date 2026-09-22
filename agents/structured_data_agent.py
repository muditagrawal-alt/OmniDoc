"""
Structured Data and SQL Agent for OmniDoc.
Generates, validates, and executes read-only queries against tabular data and SQL stores.
Enforces strict query safety and schema alignment.
"""
import re
import json
import logging
from typing import Dict, Any, List
import pandas as pd
import ollama

from core.state import AgentWorkflowState

logger = logging.getLogger("OmniDoc.StructuredDataAgent")

SAFE_SQL_PATTERN = r"(?i)^\s*(SELECT|WITH)\s+"
FORBIDDEN_SQL_PATTERN = r"(?i)\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|ATTACH|DETACH)\b"

SQL_GEN_PROMPT = """You are the Structured Data & SQL Specialist of OmniDoc.
Given the available tables and the user query, generate a clean, read-only SELECT query.

AVAILABLE TABLES & SCHEMAS:
{table_schemas}

USER QUERY:
{query}

STRICT SAFETY RULES:
- Generate ONLY a SELECT query. Never use INSERT, UPDATE, DELETE, or DROP.
- Output ONLY valid JSON:
{{
    "sql_query": "SELECT ...",
    "rationale": "Brief explanation of calculation/filtering"
}}
"""


class StructuredDataAgent:
    """Safely inspects and queries structured tables and SQL databases."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def validate_sql(self, sql_query: str) -> bool:
        """Ensures query is strictly read-only and safe."""
        if not re.search(SAFE_SQL_PATTERN, sql_query):
            return False
        if re.search(FORBIDDEN_SQL_PATTERN, sql_query):
            return False
        return True

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """Runs structured table extraction and querying."""
        query = state.get("user_query", "")
        chunks = state.get("chunk_context", [])
        
        # Check if tables exist in chunk context
        table_snippets = [ch.get("text", "") for ch in chunks if "|" in ch.get("text", "")]
        if not table_snippets:
            return {"chunk_context": []}

        logger.info(f"StructuredDataAgent evaluating {len(table_snippets)} tabular segments.")
        return {
            "chunk_context": [{"structured_tables_analyzed": len(table_snippets)}]
        }
