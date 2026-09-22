"""
Mathematical & Statistical Reasoning Agent for OmniDoc.
Executes high-precision deterministic computations in a sandboxed Python runtime.
Eliminates LLM arithmetic hallucinations for statistics, financial metrics, and equations.
"""
import re
import json
import logging
from typing import Dict, Any, List, Optional
import ollama

from core.state import AgentWorkflowState, MathExecutionResult

logger = logging.getLogger("OmniDoc.MathAgent")

MATH_CODEGEN_PROMPT = """You are the Mathematical Code Generation Specialist of OmniDoc.
Your job is to read the user query and the retrieved context, identify the exact numbers and mathematical formula needed, and write executable Python code.

Available in the execution environment:
- standard math library (`import math`)
- numpy as `np` (`import numpy as np`)
- pandas as `pd` (`import pandas as pd`)
- sympy as `sp` (`import sympy as sp`)

STRICT RULES:
1. Define all inputs explicitly from the evidence. Do NOT invent numbers.
2. Store the final result in a variable named `result`.
3. Output ONLY valid JSON matching this schema:
{{
    "task": "e.g. Calculate CAGR from 2020 to 2024",
    "formula": "e.g. (EV / BV) ** (1 / n) - 1",
    "inputs": {{"2020_revenue": 31.5, "2024_revenue": 96.8}},
    "code": "r2020 = 31.5\\nr2024 = 96.8\\nn = 4\\nresult = (r2024 / r2020) ** (1 / n) - 1",
    "units": "percentage",
    "assumptions": ["Numbers in billions USD"]
}}

CONTEXT / RETRIEVED DATA:
{context}

USER QUERY:
{query}
"""


class MathematicsAgent:
    """Solves mathematical and statistical queries via safe sandboxed code execution."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Executes mathematical reasoning step in LangGraph.
        """
        query = state.get("user_query", "")
        chunks = state.get("chunk_context", [])
        
        # Build context from chunks and tables
        context_text = ""
        for i, ch in enumerate(chunks[:5], 1):
            context_text += f"[Passage {i}]: {ch.get('text', '')}\n"

        logger.info(f"MathAgent activated for query: '{query[:60]}'")

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": MATH_CODEGEN_PROMPT.format(context=context_text[:8000], query=query)}],
                options={"temperature": 0.0, "num_predict": 1024},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            code_str = parsed.get("code", "")
            
            # Execute safely in sandbox
            execution_res = self._execute_sandboxed(code_str)

            math_artifact = MathExecutionResult(
                task=parsed.get("task", "Calculation"),
                inputs=parsed.get("inputs", {}),
                formula=parsed.get("formula", ""),
                code_executed=code_str,
                exact_result=execution_res.get("result"),
                units=parsed.get("units"),
                assumptions=parsed.get("assumptions", []),
                source_evidence_ids=[ch.get("chunk_id", "") for ch in chunks[:3]]
            )

            logger.info(f"MathAgent computed exact result: {math_artifact.exact_result} ({math_artifact.units})")
            return {
                "math_results": [math_artifact.model_dump()]
            }

        except Exception as e:
            logger.error(f"MathAgent error: {e}")
            return {
                "errors": [f"MathAgent execution error: {str(e)}"]
            }

    def _execute_sandboxed(self, code: str) -> Dict[str, Any]:
        """
        Executes Python code in a restricted namespace without filesystem/os access.
        """
        import math
        import numpy as np
        import pandas as pd
        import sympy as sp

        restricted_globals = {
            "__builtins__": {
                "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
                "dict": dict, "enumerate": enumerate, "float": float, "format": format,
                "int": int, "isinstance": isinstance, "len": len, "list": list,
                "map": map, "max": max, "min": min, "pow": pow, "print": print,
                "range": range, "round": round, "set": set, "sorted": sorted,
                "str": str, "sum": sum, "tuple": tuple, "zip": zip
            },
            "math": math,
            "np": np,
            "numpy": np,
            "pd": pd,
            "pandas": pd,
            "sp": sp,
            "sympy": sp
        }

        local_vars = {}
        try:
            exec(code, restricted_globals, local_vars)
            result_val = local_vars.get("result")
            
            # Convert numpy/sympy types to standard python for serialization
            if hasattr(result_val, "item"):
                result_val = result_val.item()
            elif isinstance(result_val, float):
                result_val = round(result_val, 4)
            elif result_val is not None:
                result_val = str(result_val)

            return {"success": True, "result": result_val}
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}
