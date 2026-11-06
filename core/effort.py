"""
How much evidence a question gets, chosen per question in the app.

"balanced" is the pipeline as benchmarked. "quick" reads fewer passages, so the answer arrives
sooner and uses fewer tokens; "thorough" retrieves and reads more, for questions whose answer is
spread over many pages. The level travels in the workflow state's `needs` next to `web_mode`.
"""
from typing import Any, Mapping

LEVELS = ("quick", "balanced", "thorough")
DEFAULT = "balanced"


def clean(value: Any) -> str:
    """A known level, or the default."""
    return value if value in LEVELS else DEFAULT


def level(state: Mapping[str, Any]) -> str:
    """The level of the question this workflow state belongs to."""
    return clean((state.get("needs") or {}).get("effort"))


def scaled(state: Mapping[str, Any], balanced: int, quick: int, thorough: int) -> int:
    """`balanced` for an ordinary question; the quick or thorough count when that level was chosen."""
    return {"quick": quick, "balanced": balanced, "thorough": thorough}[level(state)]
