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


_shared: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None


def shared_http_client() -> httpx.AsyncClient:
    """One client for downloads made while answering API requests (card images, set
    icons): its connections are kept and reused instead of a new client per request."""
    global _shared
    loop = asyncio.get_running_loop()
    if _shared is None or _shared[0] is not loop or _shared[1].is_closed:
        _shared = (loop, http_client(timeout=20))
    return _shared[1]


async def close_shared_http_client() -> None:
    global _shared
    if _shared is not None and _shared[0] is asyncio.get_running_loop():
        await _shared[1].aclose()
    _shared = None


async def _answered(_: httpx.Response) -> None:
    await progress()


async def get_with_retry(
    http: httpx.AsyncClient, url: str, attempts: int = 4, **kwargs: Any
) -> httpx.Response:
    """GET honoring Retry-After on 429 and backing off on transient server and network
    errors (timeouts, refused connections)."""
    for attempt in range(attempts):
        try:
            response = await http.get(url, **kwargs)
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(2**attempt)
            continue
        if response.status_code not in _RETRY_STATUSES or attempt == attempts - 1:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("Retry-After", "")
        delay = float(retry_after) if retry_after.isdigit() else 2**attempt
        await asyncio.sleep(min(delay, 60))
    raise AssertionError("unreachable")


async def get_limited(
    http: httpx.AsyncClient, url: str, max_bytes: int, **kwargs: Any
) -> tuple[httpx.Response, bytes | None]:
    """GET reading at most `max_bytes` of body: (response, body), body None when larger.
    Raises httpx.HTTPStatusError on an error status, like `raise_for_status`."""
    async with http.stream("GET", url, **kwargs) as response:
        response.raise_for_status()
        length = response.headers.get("content-length", "")
        if length.isdigit() and int(length) > max_bytes:
            return response, None
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                return response, None
            chunks.append(chunk)
    return response, b"".join(chunks)
