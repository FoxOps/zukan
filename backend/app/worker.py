"""Background worker: keeps catalogs, prices and images fresh.

Wakes every minute and runs each job due on the schedule administrators set on the
Data sync page (see app.services.schedule): by default when its last success is older
than `TCG_CATALOG_INTERVAL_HOURS` (catalogs) or `TCG_SYNC_INTERVAL_HOURS` (prices,
images), or at set times. Failed jobs are retried after `RETRY_AFTER`. A catalog is
also due when its provider's `catalog_version` is newer than the one of the last
successful sync (after an upgrade), and images when the catalog changed since the last
image run (new image URLs).

The schedule only follows the worker's own (`auto`) runs: manual runs neither delay nor
replace them.
"""

import asyncio
import logging
from datetime import UTC, datetime

from app.main import register_games
from app.models import JobTrigger
from app.services.jobs import JobAlreadyRunning, JobStopped, reap_runs, run_job, set_process_role
from app.services.schedule import TICK_SECONDS, is_due, jobs_for, load_schedule, worker_games

log = logging.getLogger("zukan.worker")


async def tick() -> None:
    await reap_runs()
    schedule = await load_schedule()
    for game_id in worker_games():
        for kind in jobs_for(game_id):
            if not await is_due(game_id, kind, datetime.now(UTC), schedule):
                continue
            try:
                await run_job(game_id, kind, JobTrigger.auto)
            except JobAlreadyRunning:
                log.info("%s/%s already running elsewhere", game_id, kind)
            except JobStopped:
                pass  # recorded in sync_run
            except Exception:
                # Logged and recorded in sync_run; later jobs of this game still run.
                pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    set_process_role("worker")
    await register_games()
    await reap_runs()
    while True:
        await tick()
        await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
