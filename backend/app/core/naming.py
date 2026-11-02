"""Zukan names for processes and threads, so `ps`, `top -H` and `htop` tell them apart.

The process becomes `zukan-api`, `zukan-worker` or `zukan-cli` (title and main thread),
and the threads `asyncio.to_thread` runs work in become `zukan-<role>_N` (on Python 3.14+
thread names reach the system; Linux keeps 15 characters).
"""

import asyncio
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor

from setproctitle import setproctitle, setthreadtitle

LOG_FORMAT = "%(asctime)s %(levelname)s %(processName)s/%(threadName)s %(name)s %(message)s"


def name_process(role: str) -> None:
    name = f"zukan-{role}"
    setproctitle(name)
    setthreadtitle(name)
    threading.current_thread().name = name
    # Python's own name for the process, shown by %(processName)s in logs.
    multiprocessing.current_process().name = name


def name_threads(role: str) -> None:
    """Name the worker threads of the running event loop's default executor."""
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(thread_name_prefix=f"zukan-{role}")
    )
