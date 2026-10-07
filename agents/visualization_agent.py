"""
Interactive Visualization Agent for OmniDoc.

Charts are built only from numbers that are present in the evidence. The LLM proposes a
series (labels, values and the evidence number each value came from); every value is then
checked against the text of the cited evidence item (or any other item, re-attributing the
citation), labels must be grounded in that text too, and unverified points are dropped. If
fewer than two verified points remain, no chart is returned. Emitted artifacts follow the
contract: chart_type, title, caption, plotly_spec{data, layout}, underlying_data, source_ns.
"""
import re
import math
import time
import logging
from typing import Dict, Any, List, Optional, Tuple

from core.state import AgentWorkflowState
from agents.llm_utils import chat_json, to_number, extract_numbers, number_in_text, as_list, trace
from agents.citations import sources_from_state, format_evidence_block

logger = logging.getLogger("OmniDoc.VisualizationAgent")

CHART_TYPES = ("bar", "line", "scatter", "pie")
MAX_SERIES = 3
MAX_POINTS = 30

VIZ_EXTRACTION_PROMPT = """You are the data-extraction step of OmniDoc's chart builder.
Find, in the NUMBERED EVIDENCE, a numeric series that answers the user's request.

Rules:
1. Copy every value exactly as written in the evidence (no unit conversion, no estimates, no values you computed yourself; a listed calculation result may be used).
2. For each point give the evidence number it was copied from.
3. Labels must be the category, year or name used in the evidence for that value.
4. Choose chart_type: "line" for values over time, "bar" for comparing categories, "pie" for parts of one whole, "scatter" for two numeric variables.
5. If the evidence does not contain at least two related numbers for the request, return {{"chartable": false}}.

Return JSON only:
{{"chartable": true, "chart_type": "bar", "title": "short title", "x_label": "...", "y_label": "... (unit)", "series": [{{"name": "...", "points": [{{"label": "...", "value": 12.5, "source": 1}}]}}]}}

NUMBERED EVIDENCE:
{evidence}

USER REQUEST:
{query}
"""


def _label_grounded(label: str, text: str) -> bool:
    lowered = text.lower()
    if label.lower() in lowered:
        return True
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", label.lower()) if len(t) >= 3 or t.isdigit()]
    return bool(tokens) and any(t in lowered for t in tokens)


def _verify_point(label: str, value: float, cited: Optional[int],
                  texts: Dict[int, str], numbers: Dict[int, List[float]]) -> Optional[int]:
    """Returns the evidence number that contains both value and label, or None."""
    order = ([cited] if cited in texts else []) + [n for n in texts if n != cited]
    for n in order:
        if number_in_text(value, texts[n], numbers[n]) and _label_grounded(label, texts[n]):
            return n
    return None


def _merge_single_points(singles: List[Tuple[str, List[str], List[Any], List[Dict[str, Any]]]],
                         spec: Dict[str, Any], texts: Dict[int, str]) -> Tuple[str, List[str], List[Any], List[Dict[str, Any]]]:
    """Combines one-point series into a single series labelled by series name (if grounded)."""
    merged_name = str(spec.get("y_label") or spec.get("title") or "Value").strip()[:80] or "Value"
    labels, values, rows, seen = [], [], [], set()
    for name, point_labels, point_values, point_rows in singles:
        row = point_rows[0]
        source_text = texts.get(row["source_n"], "")
        generic = name.lower() in ("", "series", "value", "values", "data")
        label = name if not generic and _label_grounded(name, source_text) else point_labels[0]
        if label.lower() in seen:
            continue
        seen.add(label.lower())
        labels.append(label)
        values.append(point_values[0])
        rows.append({**row, "label": label, "series": merged_name})
    return merged_name, labels, values, rows


def build_chart(spec: Dict[str, Any], sources: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Validates an LLM chart proposal against the evidence; returns (artifact | None, reason)."""
    if not isinstance(spec, dict) or spec.get("chartable") is False:
        return None, "evidence has no chartable numeric series"
    texts = {s["n"]: s.get("_text") or s.get("snippet") or "" for s in sources}
    numbers = {n: extract_numbers(t) for n, t in texts.items()}

    series_out = []
    dropped = 0
    for series in as_list(spec.get("series"))[:MAX_SERIES]:
        if not isinstance(series, dict):
            continue
        name = str(series.get("name") or "Series").strip()[:80]
        labels, values, rows, seen = [], [], [], set()
        for p in as_list(series.get("points"))[:MAX_POINTS]:
            if not isinstance(p, dict):
                continue
            label = str(p.get("label") if p.get("label") is not None else p.get("x", "")).strip()[:60]
            value = to_number(p.get("value", p.get("y")))
            cited = p.get("source")
            try:
                cited = int(cited) if cited is not None else None
            except (TypeError, ValueError):
                cited = None
            if not label or value is None or label.lower() in seen:
                dropped += 1
                continue
            n = _verify_point(label, value, cited, texts, numbers)
            if n is None:
                dropped += 1
                continue
            seen.add(label.lower())
            labels.append(label)
            values.append(int(value) if float(value).is_integer() and abs(value) < 1e15 else float(value))
            rows.append({"label": label, "value": values[-1], "series": name, "source_n": n})
        if values:
            series_out.append((name, labels, values, rows))

    multi = [srs for srs in series_out if len(srs[2]) >= 2]
    if multi:
        series_out = multi
    elif len(series_out) >= 2:
        # Models often give one series per category (Wind: 51, Solar: 40) for a
        # part-to-whole question; read those single points as one series.
        series_out = [_merge_single_points(series_out, spec, texts)]
    else:
        series_out = []

    if not series_out:
        return None, f"no series with >= 2 values verified in the evidence ({dropped} unverified point(s) dropped)"

    chart_type = str(spec.get("chart_type") or "bar").lower().strip()
    if chart_type not in CHART_TYPES:
        chart_type = "bar"
    if chart_type == "pie" and (len(series_out) > 1 or any(v <= 0 for v in series_out[0][2])):
        chart_type = "bar"

    x_label = str(spec.get("x_label") or "").strip()[:80]
    y_label = str(spec.get("y_label") or "").strip()[:80]
    data = []
    for name, labels, values, _ in series_out:
        if chart_type == "pie":
            data.append({"type": "pie", "name": name, "labels": labels, "values": values})
        else:
            data.append({"type": chart_type, "name": name, "x": labels, "y": values})

    underlying = [row for *_, rows in series_out for row in rows]
    source_ns = sorted({row["source_n"] for row in underlying})
    title = str(spec.get("title") or "").strip()[:120] or (series_out[0][0] if len(series_out) == 1 else "Values from the documents")
    cites = "".join(f"[{n}]" for n in source_ns)
    caption = (f"{len(underlying)} values plotted exactly as reported in source{'s' if len(source_ns) > 1 else ''} {cites}."
               + (f" {dropped} value(s) that could not be verified in the sources were omitted." if dropped else ""))

    artifact = {
        "chart_type": chart_type,
        "title": title,
        "caption": caption,
        "plotly_spec": {
            "data": data,
            "layout": {"xaxis": {"title": x_label}, "yaxis": {"title": y_label}},
        },
        "underlying_data": underlying,
        "source_ns": source_ns,
    }
    _validate_artifact(artifact)
    return artifact, f"{chart_type} chart with {len(underlying)} verified values"


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _validate_artifact(a: Dict[str, Any]) -> None:
    """Contract check; raises ValueError if the artifact is malformed."""
    _require(a["chart_type"] in CHART_TYPES, "bad chart_type")
    _require(isinstance(a["title"], str) and isinstance(a["caption"], str), "title/caption must be strings")
    data = a["plotly_spec"]["data"]
    _require(isinstance(data, list) and data, "plotly_spec.data must be a non-empty list")
    for tr in data:
        _require(tr["type"] == a["chart_type"], "trace type must equal chart_type")
        if tr["type"] == "pie":
            _require(len(tr["labels"]) == len(tr["values"]) >= 2, "pie labels/values mismatch")
            nums = tr["values"]
        else:
            _require(len(tr["x"]) == len(tr["y"]) >= 2, "x/y length mismatch")
            nums = tr["y"]
        _require(all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in nums),
                "values must be finite JSON numbers")
    _require(all(isinstance(n, int) for n in a["source_ns"]), "source_ns must be ints")


class VisualizationAgent:
    """Generates chart specifications strictly from numbers found in the evidence."""

    def __init__(self, model_name: str = "qwen2.5:7b-instruct"):
        self.model_name = model_name

    def run(self, state: AgentWorkflowState) -> Dict[str, Any]:
        """
        Executes visualization generation step in LangGraph.
        """
        started = time.perf_counter()
        semantic_q = state.get("semantic_query")
        query = getattr(semantic_q, "resolved_query", None) or state.get("user_query", "")
        sources = [s for s in sources_from_state(state) if s["kind"] in ("chunk", "graph", "math", "visual", "web")]

        numeric_values = sum(len(extract_numbers(s.get("_text", ""))) for s in sources)
        if numeric_values < 2:
            return {"visual_artifacts": [],
                    "agent_traces": [trace("visualization_agent", "skipped", "No numeric data in the evidence.", started)]}

        logger.info(f"VisualizationAgent activated for: '{query[:60]}'")
        try:
            spec = chat_json(
                self.model_name,
                VIZ_EXTRACTION_PROMPT.format(evidence=format_evidence_block(sources)[:9000], query=query),
                num_predict=900,
            )
            artifact, reason = build_chart(spec, sources)
        except Exception as e:
            logger.error(f"VisualizationAgent error: {e}")
            return {
                "visual_artifacts": [],
                "errors": [f"VisualizationAgent error: {e}"],
                "agent_traces": [trace("visualization_agent", "failed", str(e)[:200], started)],
            }

        if artifact is None:
            logger.info(f"VisualizationAgent: no chart ({reason}).")
            return {"visual_artifacts": [], "agent_traces": [trace("visualization_agent", "completed", f"No chart: {reason}", started)]}

        logger.info(f"VisualizationAgent created '{artifact['chart_type']}' chart: {artifact['title']}")
        return {
            "visual_artifacts": [artifact],
            "agent_traces": [trace("visualization_agent", "completed", reason, started)],
        }
