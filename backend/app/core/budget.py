"""Request quotas of external APIs with limited free tiers.

Each request is counted in `api_usage` before it is sent; once the period's limit is
reached the source stops (`BudgetSpent`) and tries again next period. A per-minute pace
keeps under rate limits."""

import asyncio
import time
from datetime import date
from typing import Any, Literal

import httpx
from sqlalchemy import text

from app.core.db import get_sessionmaker
from app.core.http import get_with_retry


class BudgetSpent(Exception):
    """The source used every request it may make this period."""


def period_start(period: Literal["day", "month"], today: date | None = None) -> date:
    today = today or date.today()
    return today if period == "day" else today.replace(day=1)


class RequestBudget:
    def __init__(
        self,
        source: str,
        period: Literal["day", "month"],
        limit: int,
        per_minute: int | None = None,
    ):
        self.source = source
        self.period = period
        self.limit = limit
        self.interval = 60 / per_minute if per_minute else 0.0
        self._last = 0.0
        # Requests made through this budget object (reports).
        self.used = 0

    async def _count(self, n: int) -> int:
        async with get_sessionmaker()() as session:
            total = await session.scalar(
                text(
                    "INSERT INTO api_usage (source, period_start, requests) "
                    "VALUES (:source, :start, :n) ON CONFLICT (source, period_start) "
                    "DO UPDATE SET requests = api_usage.requests + :n RETURNING requests"
                ),
                {"source": self.source, "start": period_start(self.period), "n": n},
            )
            await session.commit()
            return int(total or 0)

    async def take(self) -> None:
        """Count one request, waiting for the pace; `BudgetSpent` when none is left."""
        if await self._count(1) > self.limit:
            await self._count(-1)
            raise BudgetSpent(f"{self.source}: {self.limit} requests per {self.period} used")
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last = time.monotonic()
        self.used += 1

    async def refund(self) -> None:
        """Give back the last request taken: it never reached the source (network error)."""
        await self._count(-1)
        self.used -= 1

    async def remaining(self) -> int:
        return max(0, self.limit - await self._count(0))

    async def get(self, http: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        await self.take()
        return await get_with_retry(http, url, **kwargs)
