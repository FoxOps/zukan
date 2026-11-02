"""Give memory back once a data sync is over (worker).

A sync loads whole catalogs (hundreds of MB): providers keep some for the next job of
the same run (catalog, then prices), in module caches that otherwise lived as long as
the process. The worker calls `release()` when no job runs any more: the caches are
emptied, unreachable objects collected, and glibc returns its free pages to the system
(`malloc_trim`), so the process does not stay at its peak size until a restart.
"""

import ctypes
import gc
import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

_clearers: list[Callable[[], None]] = []


def releasable[F: Callable[[], None]](clear: F) -> F:
    """Register a function emptying a module cache (decorator)."""
    _clearers.append(clear)
    return clear


def rss_mb() -> float | None:
    """Resident memory of this process (MB), Linux only."""
    try:
        with open("/proc/self/status") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


def _malloc_trim() -> None:
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass  # not glibc


def release() -> None:
    before = rss_mb()
    for clear in _clearers:
        clear()
    gc.collect()
    _malloc_trim()
    after = rss_mb()
    if before is not None and after is not None:
        log.info("Data sync over, memory released: %.0f MB -> %.0f MB", before, after)
