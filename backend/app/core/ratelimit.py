"""In-memory sliding-window counters limiting sign-in attempts (one API process).

Keys are account names and client addresses (`request.client.host`, which uvicorn takes
from `X-Forwarded-For` only for the proxies in `FORWARDED_ALLOW_IPS`). Counters expire on
their own, so an attacker can delay an account's sign-in for one window at most, never
lock it for good.
"""

import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

# Keys kept per counter; past it the least recently hit ones are dropped.
_MAX_KEYS = 50_000


class SlidingWindow:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def _recent(self, key: str, window: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        start = self.clock() - window
        while hits and hits[0] <= start:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def retry_after(self, key: str, limit: int, window: float) -> int | None:
        """Seconds until `key` may try again, None when under `limit` (0: no limit)."""
        if limit <= 0:
            return None
        hits = self._recent(key, window)
        if hits is None or len(hits) < limit:
            return None
        return max(1, math.ceil(hits[-limit] + window - self.clock()))

    def hit(self, key: str, window: float) -> None:
        hits = self._recent(key, window) or deque()
        # Most recently hit last, so the oldest key goes first when full.
        self._hits.pop(key, None)
        if len(self._hits) >= _MAX_KEYS:
            del self._hits[next(iter(self._hits))]
        hits.append(self.clock())
        self._hits[key] = hits

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


# Failed password sign-ins per account name and per address; other sign-in requests
# (refresh, SSO) per address.
failed_by_name = SlidingWindow()
failed_by_address = SlidingWindow()
auth_by_address = SlidingWindow()


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many attempts, try again later",
        headers={"Retry-After": str(retry_after)},
    )


def limit_auth_requests(request: Request) -> None:
    """Dependency: caps refresh and SSO requests per client address."""
    from app.core.config import get_settings

    address = client_address(request)
    wait = auth_by_address.retry_after(address, get_settings().auth_requests_per_minute, 60)
    if wait is not None:
        raise too_many(wait)
    auth_by_address.hit(address, 60)
