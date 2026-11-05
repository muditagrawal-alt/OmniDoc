"""
Giving memory back after heavy work, for small (1 GB) servers.

Parsing a PDF renders scanned pages at OCR resolution and fills PyMuPDF's resource store (up to
256 MB); embedding and reranking allocate model activations. All of it is freed when the work ends,
but the C allocator keeps freed pages, so the process stays at its peak. release() empties
PyMuPDF's store and, on Linux, asks glibc to return free pages to the system (malloc_trim). The slim
image also sets MALLOC_ARENA_MAX and the trim/mmap thresholds so large buffers go back promptly.
"""
import gc
import ctypes
import logging
import sys
import threading

logger = logging.getLogger("OmniDoc.Memory")
_lock = threading.Lock()
_libc = None


def _trim() -> None:
    global _libc
    if not sys.platform.startswith("linux"):
        return
    if _libc is None:
        try:
            _libc = ctypes.CDLL("libc.so.6")
        except OSError:
            _libc = False
    if _libc:
        _libc.malloc_trim(0)


def release() -> None:
    """Frees caches and returns free memory to the system. Cheap enough to call after each upload or answer."""
    if not _lock.acquire(blocking=False):
        return  # another thread is already releasing
    try:
        gc.collect()
        try:
            import fitz
            fitz.TOOLS.store_shrink(100)
        except Exception:
            pass
        _trim()
    except Exception as e:  # never let housekeeping break a request
        logger.debug(f"Memory release skipped: {e}")
    finally:
        _lock.release()


def rss_mb() -> float:
    """This process's resident memory in MB (0 when it cannot be read)."""
    try:
        with open("/proc/self/statm") as f:
            import os
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    except Exception:
        try:
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return peak / 2**20 if sys.platform == "darwin" else peak / 1024
        except Exception:
            return 0.0
