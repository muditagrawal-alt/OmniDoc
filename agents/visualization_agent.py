"""
Interactive Visualization Agent for OmniDoc.
Generates Plotly and Altair chart specifications from verified structured data.
Supports Bar, Line, Scatter, Pie, Heatmaps, and Geospatial Maps rendered in Streamlit.
"""
import re
import json
import logging
from typing import Dict, Any, List, Optional
import ollama

from core.state import AgentWorkflowState, VisualizationArtifact

logger = logging.getLogger("OmniDoc.VisualizationAgent")

VIZ_CODEGEN_PROMPT = """You are the Data Visualization Specialist of OmniDoc.
Your job is to generate an interactive Plotly figure specification based on the provided query, retrieved data, and mathematical computations.

Supported Chart Types:
- "bar": for categorical comparisons
- "line": for time series trends or continuous changes
- "scatter": for distributions or relationships between 2 variables
- "pie": for proportional breakdowns
- "heatmap": for matrix correlations or dense tables
- "map": for geographic distributions (latitude/longitude or regions)

Rules:
1. Use ONLY the data provided in the context or math results. Do NOT invent numbers.
2. Return a valid Plotly JSON dictionary (with "data" and "layout" keys) that can be passed directly to Plotly.
3. The layout MUST include a clean title, axis labels, and responsive layout.
4. Output ONLY valid JSON matching this schema:
{{
    "chart_type": "bar" | "line" | "scatter" | "pie" | "heatmap" | "map",
    "title": "Clean, descriptive chart title",
    "plotly_spec": {{
        "data": [
            {{
                "type": "bar",
                "x": ["2020", "2021", "2022", "2023", "2024"],
                "y": [31.5, 53.8, 81.5, 96.8, 105.2],
                "name": "Series Name"
            }}
        ],
        "layout": {{
            "title": "Chart Title",
            "xaxis": {{"title": "X-Axis Label"}},
            "yaxis": {{"title": "Y-Axis Label"}},
            "template": "plotly_white"
        }}
    }},
    "caption": "Brief summary of key visual trends",
    "underlying_data": [
        {{"x": "2020", "y": 31.5}}
    ]
}}

EVIDENCE CONTEXT:
{context}

USER QUERY:
{query}
"""


class VisualizationAgent:
    """Generates interactive Plotly visualizations from verified data."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Executes visualization generation step in LangGraph.
        """
        query = state.get("user_query", "")
        chunks = state.get("chunk_context", [])
        math_res = state.get("math_results", [])
        
        # Build context
        context_parts = []
        if math_res:
            context_parts.append(f"=== MATHEMATICAL RESULTS ===\n{json.dumps(math_res, indent=2)}")
        
        if chunks:
            context_parts.append("=== RETRIEVED TABLE & TEXT EVIDENCE ===")
            for ch in chunks[:4]:
                context_parts.append(ch.get("text", ""))

        combined_context = "\n\n".join(context_parts)
        logger.info(f"VisualizationAgent activated for: '{query[:60]}'")

        try:
            prompt = VIZ_CODEGEN_PROMPT.format(context=combined_context[:8000], query=query)
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "num_predict": 1024},
                stream=False
            )
            raw = response["message"]["content"].strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)

            parsed = json.loads(raw)
            artifact = VisualizationArtifact(
                chart_type=parsed.get("chart_type", "bar"),
                title=parsed.get("title", "Data Visualization"),
                plotly_spec=parsed.get("plotly_spec", {}),
                underlying_data=parsed.get("underlying_data", []),
                caption=parsed.get("caption", "")
            )

            logger.info(f"VisualizationAgent created '{artifact.chart_type}' chart: {artifact.title}")
            return {
                "visual_artifacts": [artifact.model_dump()]
            }

        except Exception as e:
            logger.error(f"VisualizationAgent generation error: {e}")
            return {
                "errors": [f"VisualizationAgent error: {str(e)}"]
            }
