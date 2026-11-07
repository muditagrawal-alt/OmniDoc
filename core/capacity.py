"""
Staying responsive under heavy traffic, on one server and free model quotas.

* Slots: at most OMNIDOC_MAX_ANSWERS answers (default 6) and OMNIDOC_MAX_UPLOADS uploads (default 2)
  are worked on at once. A request waits up to OMNIDOC_QUEUE_SECONDS (default 25) for a slot and is
  then turned away with a clear "busy, try again" instead of piling onto the CPU, the memory and the
  model providers' rate limits until everything slows down for everyone.
* AnswerCache: the demo's sample library is the same for every visitor, and visitors mostly ask the
  suggested questions. The first answer to a question is recorded (every streamed event and the final
  result) and replayed for the next visitors who ask the same first question with the same settings:
  instantly, and without a model call. Only first turns are cached (no conversation history), only
  for the demo library, for OMNIDOC_DEMO_CACHE_HOURS (default 12), and at most 256 answers.
"""
import os
import re
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple


class Busy(Exception):
    """No slot became free in time."""

    def __init__(self, kind: str, retry_after: int = 30):
        super().__init__(kind)
        self.kind = kind
        self.retry_after = retry_after


class Slots:
    def __init__(self, kind: str, size: int):
        self.kind = kind
        self.size = max(1, size)
        self._sem = threading.BoundedSemaphore(self.size)
        self._lock = threading.Lock()
        self.active = 0
        self.waiting = 0

    def acquire(self, timeout: float) -> bool:
        with self._lock:
            self.waiting += 1
        try:
            ok = self._sem.acquire(timeout=max(0.0, timeout))
        finally:
            with self._lock:
                self.waiting -= 1
                if ok:
                    self.active += 1
        return ok

    def release(self) -> None:
        with self._lock:
            self.active -= 1
        self._sem.release()

    @contextmanager
    def slot(self, timeout: Optional[float] = None) -> Iterator[None]:
        if not self.acquire(queue_seconds() if timeout is None else timeout):
            raise Busy(self.kind)
        try:
            yield
        finally:
            self.release()


def queue_seconds() -> float:
    return float(os.getenv("OMNIDOC_QUEUE_SECONDS", "25"))


ANSWERS = Slots("answers", int(os.getenv("OMNIDOC_MAX_ANSWERS", "6")))
UPLOADS = Slots("uploads", int(os.getenv("OMNIDOC_MAX_UPLOADS", "2")))


class AnswerCache:
    def __init__(self, size: int = 256):
        self.size = size
        self._items: "OrderedDict[Tuple, Tuple[float, List[Tuple[str, Any]], Dict[str, Any]]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(query: str, doc_ids: Sequence[str], **settings: Any) -> Tuple:
        words = re.sub(r"\s+", " ", (query or "").strip().lower()).rstrip(" ?.!")
        return (words, tuple(sorted(doc_ids or ())), tuple(sorted((k, str(v)) for k, v in settings.items())))

    def get(self, key: Tuple) -> Optional[Tuple[List[Tuple[str, Any]], Dict[str, Any]]]:
        ttl = float(os.getenv("OMNIDOC_DEMO_CACHE_HOURS", "12")) * 3600
        with self._lock:
            item = self._items.get(key)
            if not item or time.time() - item[0] > ttl:
                if item:
                    del self._items[key]
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            return item[1], item[2]

    def put(self, key: Tuple, events: List[Tuple[str, Any]], payload: Dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = (time.time(), events, payload)
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


DEMO_ANSWERS = AnswerCache()


def stats() -> Dict[str, Any]:
    """For the administrator: how busy the server is right now."""
    return {
        "answers": {"active": ANSWERS.active, "waiting": ANSWERS.waiting, "limit": ANSWERS.size},
        "uploads": {"active": UPLOADS.active, "waiting": UPLOADS.waiting, "limit": UPLOADS.size},
        "demo_cache": {"answers": len(DEMO_ANSWERS._items), "hits": DEMO_ANSWERS.hits, "misses": DEMO_ANSWERS.misses},
    }
