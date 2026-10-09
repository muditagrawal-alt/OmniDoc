"""
Per-question event channel.

The workflow runs in a worker thread; agents deep inside it (the writer) push events for
the client through this channel while the graph is still running: the numbered sources,
pieces of the answer as they are written, and a reset when a draft is replaced.
"""
import threading
from typing import Any, Callable, Dict

_lock = threading.Lock()
_channels: Dict[str, Callable[[str, Any], None]] = {}


def open_channel(run_id: str, emit: Callable[[str, Any], None]) -> None:
    with _lock:
        _channels[run_id] = emit


def close_channel(run_id: str) -> None:
    with _lock:
        _channels.pop(run_id, None)


def emit(run_id: str, event: str, data: Any = None) -> bool:
    """Sends an event to the client of a run; False when nobody is listening."""
    with _lock:
        sink = _channels.get(run_id or "")
    if sink is None:
        return False
    sink(event, data)
    return True


def listening(run_id: str) -> bool:
    with _lock:
        return (run_id or "") in _channels
