"""When the worker runs each job (see app.worker): shared with the admin API, which
shows the next run and edits the schedule.

Each job kind follows a rule set by administrators on the Data sync page (stored in
`app_setting`, key `sync_schedule`): every N hours since the last run (the default, from
`TCG_*_INTERVAL_HOURS`), or at set times every day, on some days of the week, or once a
month, in the schedule's time zone."""

import logging
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.games.base import catalog_version, group_of, registry
from app.models import AppSetting, JobKind, JobStatus, JobTrigger, SyncRun
from app.services.prices import has_prices
from app.services.refresh import can_refresh

log = logging.getLogger("zukan.schedule")

# The worker checks every minute, so jobs set at 04:30 start at 04:30.
TICK_SECONDS = 60
RETRY_AFTER = timedelta(hours=1)
SETTING_KEY = "sync_schedule"
# Days searched for the previous / next set time (a monthly rule has one within 31).
_SEARCH_DAYS = 62
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleRule(BaseModel):
    """When one job kind runs. `interval`: `every_hours` after the last run started.
    Other modes: at each of `times` (local "HH:MM") every day (`daily`), on `weekdays`
    (0 Monday .. 6 Sunday, `weekly`) or on `month_day` (`monthly`)."""

    mode: Literal["interval", "daily", "weekly", "monthly"] = "interval"
    every_hours: int = Field(24, ge=1, le=31 * 24)
    times: list[str] = Field(default_factory=lambda: ["03:00"], min_length=1, max_length=24)
    weekdays: list[int] = Field(default_factory=lambda: [0], min_length=1, max_length=7)
    month_day: int = Field(1, ge=1, le=28)

    @field_validator("times")
    @classmethod
    def _times(cls, value: list[str]) -> list[str]:
        for t in value:
            if not _TIME.match(t):
                raise ValueError(f"Invalid time {t!r}, expected HH:MM")
        return sorted(set(value))

    @field_validator("weekdays")
    @classmethod
    def _weekdays(cls, value: list[int]) -> list[int]:
        if any(not 0 <= d <= 6 for d in value):
            raise ValueError("Weekdays go from 0 (Monday) to 6 (Sunday)")
        return sorted(set(value))

    def runs_on(self, day: date) -> bool:
        if self.mode == "weekly":
            return day.weekday() in self.weekdays
        if self.mode == "monthly":
            return day.day == self.month_day
        return True


class SyncSchedule(BaseModel):
    timezone: str
    jobs: dict[JobKind, ScheduleRule]
    # When it was last saved: set times before it are not caught up.
    updated_at: datetime | None = None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        if value != "UTC" and value not in available_timezones():
            raise ValueError(f"Unknown time zone {value!r}")
        return value

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def default_timezone() -> str:
    name = get_settings().schedule_timezone
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("TCG_SCHEDULE_TIMEZONE %r unknown, using UTC", name)
        return "UTC"
    return name


def default_schedule() -> SyncSchedule:
    """Every N hours, from the TCG_*_INTERVAL_HOURS variables."""
    settings = get_settings()
    hours = {
        JobKind.catalog: settings.catalog_interval_hours,
        JobKind.prices: settings.sync_interval_hours,
        JobKind.images: settings.sync_interval_hours,
        JobKind.refresh: settings.refresh_interval_hours,
    }
    return SyncSchedule(
        timezone=default_timezone(),
        jobs={kind: ScheduleRule(every_hours=max(1, h)) for kind, h in hours.items()},
    )


async def load_schedule() -> SyncSchedule:
    """Saved schedule; job kinds missing from it follow their default rule."""
    default = default_schedule()
    async with get_sessionmaker()() as session:
        row = await session.get(AppSetting, SETTING_KEY)
    if row is None:
        return default
    try:
        saved = SyncSchedule.model_validate({**row.value, "updated_at": row.updated_at})
    except ValidationError:
        log.exception("Saved sync schedule is invalid, using the default one")
        return default
    return saved.model_copy(update={"jobs": {**default.jobs, **saved.jobs}})


async def save_schedule(schedule: SyncSchedule | None) -> SyncSchedule:
    """Store the schedule; None goes back to the default one."""
    async with get_sessionmaker()() as session:
        row = await session.get(AppSetting, SETTING_KEY)
        if schedule is None:
            if row is not None:
                await session.delete(row)
        else:
            value = schedule.model_dump(mode="json", exclude={"updated_at"})
            if row is None:
                session.add(AppSetting(key=SETTING_KEY, value=value))
            else:
                row.value = value
                row.updated_at = datetime.now(UTC)
        await session.commit()
    return await load_schedule()


def _slots(rule: ScheduleRule, zone: ZoneInfo, day: date) -> list[datetime]:
    if not rule.runs_on(day):
        return []
    return [
        datetime.combine(day, time.fromisoformat(t), tzinfo=zone).astimezone(UTC)
        for t in rule.times
    ]


def previous_slot(rule: ScheduleRule, zone: ZoneInfo, now: datetime) -> datetime | None:
    """Last set time at or before `now` (fixed-time modes)."""
    today = now.astimezone(zone).date()
    for offset in range(_SEARCH_DAYS):
        slots = [s for s in _slots(rule, zone, today - timedelta(days=offset)) if s <= now]
        if slots:
            return max(slots)
    return None


def next_slot(rule: ScheduleRule, zone: ZoneInfo, now: datetime) -> datetime | None:
    """First set time after `now` (fixed-time modes)."""
    today = now.astimezone(zone).date()
    for offset in range(_SEARCH_DAYS):
        slots = [s for s in _slots(rule, zone, today + timedelta(days=offset)) if s > now]
        if slots:
            return min(slots)
    return None


def upcoming(rule: ScheduleRule, zone: ZoneInfo, now: datetime, count: int = 3) -> list[datetime]:
    """Next set times of a fixed-time rule (preview on the admin page)."""
    out: list[datetime] = []
    at: datetime | None = now
    while len(out) < count and (at := next_slot(rule, zone, at)) is not None:
        out.append(at)
    return out


def worker_games() -> list[str]:
    """Games the worker refreshes (`TCG_WORKER_GAMES`, empty: all). A group's own id listed
    alone ("pokemon", one game before 0.17.0) stands for every game of the group, unless
    other games of the group are listed too."""
    listed = get_settings().worker_games
    if not listed:
        return list(registry())
    games: list[str] = []
    for game_id in listed:
        members = [g for g in registry() if group_of(g) == group_of(game_id)]
        alone = not any(m in listed for m in members if m != game_id)
        games += members if game_id == group_of(game_id) and alone else [game_id]
    return [g for g in dict.fromkeys(games) if g in registry()]


async def _last_attempt(game_id: str, kind: JobKind) -> datetime | None:
    """Start of the last auto run that did not end cancelled (a cancelled run is retried
    at once)."""
    query = select(func.max(SyncRun.started_at)).where(
        SyncRun.game_id == game_id,
        SyncRun.kind == kind,
        SyncRun.trigger == JobTrigger.auto,
        SyncRun.status != JobStatus.cancelled,
    )
    async with get_sessionmaker()() as session:
        return await session.scalar(query)


async def _last_success(game_id: str, kind: JobKind, auto_only: bool = True) -> SyncRun | None:
    query = select(SyncRun).where(
        SyncRun.game_id == game_id,
        SyncRun.kind == kind,
        SyncRun.status == JobStatus.success,
    )
    if auto_only:
        query = query.where(SyncRun.trigger == JobTrigger.auto)
    async with get_sessionmaker()() as session:
        return await session.scalar(query.order_by(SyncRun.started_at.desc()).limit(1))


async def _outdated(game_id: str, kind: JobKind, last_success: SyncRun) -> bool:
    """Stored data older than the code (catalog) or than the catalog (images). Manual runs
    count here: the data they stored is what is checked."""
    if kind == JobKind.catalog:
        latest = await _last_success(game_id, kind, auto_only=False) or last_success
        stored = (latest.report or {}).get("catalog_version", 1)
        return stored < catalog_version(registry()[game_id])
    if kind == JobKind.images:
        catalog = await _last_success(game_id, JobKind.catalog, auto_only=False)
        images = await _last_success(game_id, kind, auto_only=False) or last_success
        return catalog is not None and catalog.started_at > images.started_at
    return False


def _waits_until(
    schedule: SyncSchedule, kind: JobKind, last_run: datetime, now: datetime
) -> datetime | None:
    """When a job whose last run started at `last_run` is due again; None: due now."""
    rule = schedule.jobs[kind]
    if rule.mode == "interval":
        due = last_run + timedelta(hours=rule.every_hours)
        return due if due > now else None
    slot = previous_slot(rule, schedule.zone, now)
    # A set time passed since the last run, and since the schedule was saved (a new
    # schedule does not catch up the times it would have had before).
    since = max(last_run, schedule.updated_at or last_run)
    if slot is not None and slot > since:
        return None
    return next_slot(rule, schedule.zone, now)


async def is_due(
    game_id: str, kind: JobKind, now: datetime, schedule: SyncSchedule | None = None
) -> bool:
    schedule = schedule or await load_schedule()
    last_success = await _last_success(game_id, kind)
    if (
        last_success is not None
        and _waits_until(schedule, kind, last_success.started_at, now) is not None
        and not await _outdated(game_id, kind, last_success)
    ):
        return False
    last_attempt = await _last_attempt(game_id, kind)
    return last_attempt is None or now - last_attempt >= RETRY_AFTER


def jobs_for(game_id: str) -> list[JobKind]:
    kinds = [JobKind.catalog]
    if has_prices(registry()[game_id]):
        kinds.append(JobKind.prices)
    kinds.append(JobKind.images)
    if can_refresh(registry()[game_id]):
        kinds.append(JobKind.refresh)
    return kinds


async def next_run(
    game_id: str, kind: JobKind, now: datetime, schedule: SyncSchedule | None = None
) -> datetime | None:
    """When the worker will start this job (at its first check from then on, every
    TICK_SECONDS); None when the worker does not run it."""
    if game_id not in worker_games() or kind not in jobs_for(game_id):
        return None
    schedule = schedule or await load_schedule()
    last_success = await _last_success(game_id, kind)
    if last_success is not None and not await _outdated(game_id, kind, last_success):
        due = _waits_until(schedule, kind, last_success.started_at, now)
        if due is not None:
            return due
    last_attempt = await _last_attempt(game_id, kind)
    if last_attempt is not None and now - last_attempt < RETRY_AFTER:
        return last_attempt + RETRY_AFTER
    return now
