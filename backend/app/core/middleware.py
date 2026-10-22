"""ASGI middlewares: security headers on every response, request body size limit."""

import json

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

_HEADERS = {
    b"x-frame-options": b"DENY",
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"same-origin",
}
_NO_FRAMING = b"frame-ancestors 'none'"


class SecurityHeaders:
    """No page of the site may be framed (clickjacking), no type sniffing, no full URL
    sent to other sites. A route's own Content-Security-Policy gets `frame-ancestors`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k.lower(), v) for k, v in message.get("headers", [])]
                present = {k for k, _ in headers}
                headers += [(k, v) for k, v in _HEADERS.items() if k not in present]
                csp = next(
                    (i for i, (k, _) in enumerate(headers) if k == b"content-security-policy"), None
                )
                if csp is None:
                    headers.append((b"content-security-policy", _NO_FRAMING))
                elif b"frame-ancestors" not in headers[csp][1]:
                    headers[csp] = (headers[csp][0], headers[csp][1] + b"; " + _NO_FRAMING)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyLimit:
    """Refuses request bodies over `TCG_MAX_REQUEST_BYTES` with 413, before they are
    parsed (multipart uploads would otherwise be spooled to disk first)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = get_settings().max_request_bytes
        length = dict(scope.get("headers", [])).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            return await _too_large(send, limit)
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # FastAPI turns it into the 413 answer.
                    raise HTTPException(413, _message(limit))
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except HTTPException as exc:
            if exc.status_code != 413 or started:
                raise
            await _too_large(send, limit)


def _message(limit: int) -> str:
    return f"Request larger than {limit // (1024 * 1024)} MB"


async def _too_large(send: Send, limit: int) -> None:
    body = json.dumps({"detail": _message(limit)}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
