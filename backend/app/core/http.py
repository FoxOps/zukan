import asyncio
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.progress import progress

_RETRY_STATUSES = {429, 500, 502, 503, 504}


def http_client(timeout: float = 60) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": get_settings().user_agent, "Accept": "application/json"},
        # Every answer counts as progress for the running job (stall detection).
        event_hooks={"response": [_answered]},
    )


async def _answered(_: httpx.Response) -> None:
    await progress()


async def get_with_retry(
    http: httpx.AsyncClient, url: str, attempts: int = 4, **kwargs: Any
) -> httpx.Response:
    """GET honoring Retry-After on 429 and backing off on transient server errors."""
    for attempt in range(attempts):
        response = await http.get(url, **kwargs)
        if response.status_code not in _RETRY_STATUSES or attempt == attempts - 1:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("Retry-After", "")
        delay = float(retry_after) if retry_after.isdigit() else 2**attempt
        await asyncio.sleep(min(delay, 60))
    raise AssertionError("unreachable")
