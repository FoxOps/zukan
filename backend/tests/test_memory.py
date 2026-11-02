import asyncio
import importlib
import threading
from concurrent.futures import ThreadPoolExecutor

from app import worker
from app.core import memory, naming
from app.games.pokemon import shared as pokemon_shared
from app.games.yugioh import shared as yugioh_shared

# The packages export their provider instance under the module's name.
riftbound = importlib.import_module("app.games.riftbound.provider")
sorcery = importlib.import_module("app.games.sorcery.provider")
yugioh = importlib.import_module("app.games.yugioh.provider")


def test_release_empties_the_catalog_caches():
    yugioh._cached = (0.0, object())
    yugioh_shared._cards = (0.0, [{}])
    yugioh_shared._ygojson = (0.0, None)
    sorcery._cached_catalog = (0.0, object())
    riftbound._cached = (0.0, object(), {})
    pokemon_shared._cached = (0.0, object())
    memory.release()
    assert yugioh._cached is None
    assert yugioh_shared._cards is None and yugioh_shared._ygojson is None
    assert sorcery._cached_catalog is None
    assert riftbound._cached is None
    assert pokemon_shared._cached is None
    assert memory.rss_mb() is None or memory.rss_mb() > 0


def test_worker_releases_once_no_job_runs(monkeypatch):
    released = []
    monkeypatch.setattr(memory, "release", lambda: released.append(1))
    monkeypatch.setattr(worker, "queued_runs_active", lambda: True)
    worker.release_if_idle()
    monkeypatch.setattr(worker, "_ticking", True)
    monkeypatch.setattr(worker, "queued_runs_active", lambda: False)
    worker.release_if_idle()
    assert released == []
    monkeypatch.setattr(worker, "_ticking", False)
    worker.release_if_idle()
    assert released == [1]


async def test_threads_are_named_after_zukan():
    loop = asyncio.get_running_loop()
    naming.name_threads("test")
    try:
        assert await asyncio.to_thread(lambda: threading.current_thread().name) == "zukan-test_0"
    finally:
        loop.set_default_executor(ThreadPoolExecutor())
