"""
Execution Guardrail and Budget Controller.

Every question gets a budget of model calls and seconds. Essential steps (understanding,
writing the answer, checking it) always run; optional ones (reading figures, auditing
conflicts, charts, a rewrite after verification) run only while budget remains, so a slow
or rate-limited provider shortens the work instead of stalling the answer. Model usage is
read from the provider layer's per-run statistics.
"""
import os
import time
import logging
from typing import Any, Callable, Dict

from agents import llm_providers

logger = logging.getLogger("OmniDoc.ExecutionGuard")

MAX_LLM_CALLS = int(os.getenv("OMNIDOC_MAX_LLM_CALLS", "8"))
MAX_SECONDS = float(os.getenv("OMNIDOC_MAX_SECONDS", "180"))


class ExecutionBudgetGuard:
    """Monitors resource consumption and prevents infinite agent loops."""

    def __init__(
        self,
        max_iterations: int = 3,
        max_context_chars: int = 24000,
        tool_timeout_seconds: float = 15.0,
        max_llm_calls: int = MAX_LLM_CALLS,
        max_seconds: float = MAX_SECONDS,
    ):
        self.max_iterations = max_iterations
        self.max_context_chars = max_context_chars
        self.tool_timeout_seconds = tool_timeout_seconds
        self.max_llm_calls = max_llm_calls
        self.max_seconds = max_seconds
        self._started: Dict[str, float] = {}

    # --------------------------------------------------------------- per-question budget
    def start(self, run_id: str) -> None:
        self._started[run_id] = time.time()

    def usage(self, run_id: str) -> Dict[str, Any]:
        stats = llm_providers.run_stats(run_id)
        stats["elapsed_s"] = round(time.time() - self._started.get(run_id, time.time()), 1)
        return stats

    def allow(self, run_id: str, step: str, calls: int = 1, essential: bool = False) -> bool:
        """Whether a step that needs ``calls`` model calls may run now."""
        if essential or not run_id:
            return True
        used = self.usage(run_id)
        if used["calls"] + calls > self.max_llm_calls:
            logger.info(f"Budget: skipping {step} ({used['calls']} of {self.max_llm_calls} model calls used).")
            return False
        if used["elapsed_s"] > self.max_seconds * 0.6:
            logger.info(f"Budget: skipping {step} ({used['elapsed_s']}s of {self.max_seconds}s used).")
            return False
        return True

    def finish(self, run_id: str) -> Dict[str, Any]:
        stats = self.usage(run_id)
        self._started.pop(run_id, None)
        llm_providers.run_stats(run_id, pop=True)
        return stats

    # ------------------------------------------------------------------- older helpers
    def should_terminate(self, iteration_count: int) -> bool:
        """Determines if the agent reflection loop must be halted."""
        if iteration_count >= self.max_iterations:
            logger.warning(f"Execution cap reached: {iteration_count}/{self.max_iterations} iterations.")
            return True
        return False

    def trim_context_to_budget(self, text: str) -> str:
        """Truncates context if it exceeds the character budget."""
        if len(text) > self.max_context_chars:
            logger.info(f"Context trimmed from {len(text)} to {self.max_context_chars} chars.")
            return text[:self.max_context_chars] + "\n...[Context truncated to fit the budget]..."
        return text

    def run_safe_tool(self, tool_func: Callable, *args, **kwargs) -> Any:
        """Wraps tool execution with error containment and timing."""
        start_time = time.time()
        try:
            result = tool_func(*args, **kwargs)
            duration = time.time() - start_time
            if duration > self.tool_timeout_seconds:
                logger.warning(f"Tool {tool_func.__name__} took {duration:.2f}s (budget: {self.tool_timeout_seconds}s)")
            return result
        except Exception as e:
            logger.error(f"Error executing tool {tool_func.__name__}: {e}")
            return {"error": str(e), "success": False}
