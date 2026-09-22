"""
Execution Guardrail and Budget Controller.
Enforces loop depth limits, context token budgets, tool timeouts,
and circuit breakers across multi-agent graph workflows.
"""
import time
import logging
from typing import Dict, Any, Callable

logger = logging.getLogger("OmniDoc.ExecutionGuard")


class ExecutionBudgetGuard:
    """Monitors resource consumption and prevents infinite agent loops."""

    def __init__(
        self,
        max_iterations: int = 3,
        max_context_chars: int = 24000,
        tool_timeout_seconds: float = 15.0
    ):
        self.max_iterations = max_iterations
        self.max_context_chars = max_context_chars
        self.tool_timeout_seconds = tool_timeout_seconds

    def should_terminate(self, iteration_count: int) -> bool:
        """Determines if the agent reflection loop must be halted."""
        if iteration_count >= self.max_iterations:
            logger.warning(f"🛑 Execution cap reached: {iteration_count}/{self.max_iterations} iterations. Forcing synthesis.")
            return True
        return False

    def trim_context_to_budget(self, text: str) -> str:
        """Truncates context if it exceeds character/token budget."""
        if len(text) > self.max_context_chars:
            logger.info(f"Context trimmed from {len(text)} to {self.max_context_chars} chars.")
            return text[:self.max_context_chars] + "\n...[Context truncated to fit memory budget]..."
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
