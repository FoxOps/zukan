"""Sync schedule at set times (admin Data sync page) and the worker following it."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.games.base import get_provider
from app.models import JobKind, JobStatus, JobTrigger, Role, SyncRun
from app.services import schedule
from app.services.schedule import ScheduleRule, SyncSchedule, next_slot, previous_slot, upcoming
from tests.conftest import bearer, make_user

PARIS = ZoneInfo("Europe/Paris")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def test_daily_weekly_monthly_slots():
    daily = ScheduleRule(mode="daily", times=["18:00", "04:30", "04:30"])
    assert daily.times == ["04:30", "18:00"]
    now = at("2026-10-27T10:00:00+01:00")
    assert previous_slot(daily, PARIS, now) == at("2026-10-27T04:30:00+01:00")
    assert next_slot(daily, PARIS, now) == at("2026-10-27T18:00:00+01:00")

    weekly = ScheduleRule(mode="weekly", times=["03:00"], weekdays=[0, 4])  # Mon, Fri
    assert upcoming(weekly, PARIS, now) == [
        at("2026-10-30T03:00:00+01:00"),
        at("2026-11-02T03:00:00+01:00"),
        at("2026-11-06T03:00:00+01:00"),
    ]
    monthly = ScheduleRule(mode="monthly", times=["02:00"], month_day=1)
    assert next_slot(monthly, PARIS, now) == at("2026-11-01T02:00:00+01:00")
    assert previous_slot(monthly, PARIS, now) == at("2026-10-01T02:00:00+02:00")


def test_slots_follow_daylight_saving_time():
    # Paris left summer time on 2026-10-25 at 03:00: 04:30 local is 02:30 UTC before,
    # 03:30 UTC from that day on.
    daily = ScheduleRule(mode="daily", times=["04:30"])
    assert next_slot(daily, PARIS, at("2026-10-23T12:00:00+00:00")) == at(
        "2026-10-24T02:30:00+00:00"
    )
    assert next_slot(daily, PARIS, at("2026-10-24T12:00:00+00:00")) == at(
        "2026-10-25T03:30:00+00:00"
    )


def test_invalid_rules_refused():
    with pytest.raises(ValidationError):
        ScheduleRule(mode="daily", times=["25:00"])
    with pytest.raises(ValidationError):
        ScheduleRule(mode="weekly", weekdays=[])
    with pytest.raises(ValidationError):
        ScheduleRule(mode="weekly", weekdays=[7])
    with pytest.raises(ValidationError):
        SyncSchedule(timezone="Mars/Olympus", jobs={})


async def test_worker_runs_at_set_times(session):
    from app.main import register_games

    await register_games()
    current = {"catalog_version": get_provider("sorcery").catalog_version}
    saved_at = at("2026-10-26T12:00:00+00:00")
    rules = SyncSchedule(
        timezone="UTC",
        jobs={
            **schedule.default_schedule().jobs,
            JobKind.catalog: ScheduleRule(mode="daily", times=["04:30"]),
        },
        updated_at=saved_at,
    )
    # Never synced: at once, whatever the schedule.
    assert await schedule.is_due("sorcery", JobKind.catalog, saved_at, rules)
    session.add(
        SyncRun(
            game_id="sorcery",
            kind=JobKind.catalog,
            trigger=JobTrigger.auto,
            status=JobStatus.success,
            started_at=at("2026-10-26T08:00:00+00:00"),
            report=current,
        )
    )
    await session.commit()
    # Today's 04:30 passed before the schedule was saved: not caught up.
    assert not await schedule.is_due("sorcery", JobKind.catalog, saved_at, rules)
    assert await schedule.next_run("sorcery", JobKind.catalog, saved_at, rules) == at(
        "2026-10-27T04:30:00+00:00"
    )
    assert not await schedule.is_due(
        "sorcery", JobKind.catalog, at("2026-10-27T04:29:00+00:00"), rules
    )
    assert await schedule.is_due("sorcery", JobKind.catalog, at("2026-10-27T04:31:00+00:00"), rules)

    # Run at 04:31: not due again until tomorrow.
    session.add(
        SyncRun(
            game_id="sorcery",
            kind=JobKind.catalog,
            trigger=JobTrigger.auto,
            status=JobStatus.success,
            started_at=at("2026-10-27T04:31:00+00:00"),
            report=current,
        )
    )
    await session.commit()
    later = at("2026-10-27T20:00:00+00:00")
    assert not await schedule.is_due("sorcery", JobKind.catalog, later, rules)
    assert await schedule.is_due("sorcery", JobKind.catalog, later + timedelta(hours=9), rules)


async def test_schedule_api(client, session):
    from app.main import register_games

    await register_games()
    await make_user(session, "root", role=Role.admin)
    admin = await bearer(client, "root")
    body = (await client.get("/api/admin/sync-schedule", headers=admin)).json()
    assert body["is_default"] is True and body["timezone"] == "UTC"
    assert body["jobs"]["catalog"] == {
        "mode": "interval",
        "every_hours": 168,
        "times": ["03:00"],
        "weekdays": [0],
        "month_day": 1,
    }

    edited = {
        "timezone": "Europe/Paris",
        "jobs": {"prices": {"mode": "weekly", "times": ["06:00", "18:00"], "weekdays": [5, 6]}},
    }
    preview = await client.post("/api/admin/sync-schedule/preview", json=edited, headers=admin)
    assert len(preview.json()["upcoming"]["prices"]) == 3
    assert (await client.get("/api/admin/sync-schedule", headers=admin)).json()["is_default"]

    saved = (await client.put("/api/admin/sync-schedule", json=edited, headers=admin)).json()
    assert saved["is_default"] is False and saved["timezone"] == "Europe/Paris"
    assert saved["jobs"]["prices"]["weekdays"] == [5, 6]
    assert saved["jobs"]["catalog"]["mode"] == "interval"  # left out: default
    loaded = await schedule.load_schedule()
    assert loaded.jobs[JobKind.prices].mode == "weekly" and loaded.updated_at is not None
    next_runs = (await client.get("/api/admin/schedule", headers=admin)).json()
    assert next_runs and all(r["check_seconds"] == 60 for r in next_runs)

    bad = {"timezone": "Nowhere/Land", "jobs": {}}
    assert (
        await client.put("/api/admin/sync-schedule", json=bad, headers=admin)
    ).status_code == 422
    bad = {"timezone": "UTC", "jobs": {"prices": {"mode": "daily", "times": ["7h"]}}}
    assert (
        await client.put("/api/admin/sync-schedule", json=bad, headers=admin)
    ).status_code == 422

    reset = (await client.delete("/api/admin/sync-schedule", headers=admin)).json()
    assert reset["is_default"] is True and reset["jobs"]["prices"]["mode"] == "interval"

    user = await make_user(session, "bob")
    assert user.role == Role.user
    denied = await client.get("/api/admin/sync-schedule", headers=await bearer(client, "bob"))
    assert denied.status_code == 403


def test_now_is_aware():
    # Rules compare with aware datetimes from the worker.
    rule = ScheduleRule(mode="daily", times=["00:00"])
    assert next_slot(rule, ZoneInfo("UTC"), datetime.now(UTC)).tzinfo is not None
