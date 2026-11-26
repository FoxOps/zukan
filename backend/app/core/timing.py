"""Stage durations of one request, sent as a `Server-Timing` header (browser developer
tools show them next to the request): which part of a slow search takes the time."""

import time

from fastapi import Response


class Stages:
    def __init__(self) -> None:
        self._last = time.perf_counter()
        self._spent: list[tuple[str, float]] = []

    def mark(self, name: str) -> None:
        """End of stage `name` (since the previous mark)."""
        now = time.perf_counter()
        self._spent.append((name, (now - self._last) * 1000))
        self._last = now

    def header(self) -> str:
        return ", ".join(f"{name};dur={ms:.1f}" for name, ms in self._spent)

    def send(self, response: Response) -> None:
        response.headers["Server-Timing"] = self.header()
