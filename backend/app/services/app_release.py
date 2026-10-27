"""Latest Android app release on GitHub (`android-vX.Y.Z` tags, asset `zukan-X.Y.Z.apk`),
offered for download by the web interface and to the app's update check.

Server and app releases share the repository, so GitHub's "latest release" may be a
server one: releases are listed and the newest Android one is picked."""

import logging
import re
import time
from datetime import datetime

import httpx
from pydantic import BaseModel

from app.core.config import get_settings

log = logging.getLogger("zukan.app_release")

_TAG = re.compile(r"^android-v(\d+)\.(\d+)\.(\d+)$")
_APK = re.compile(r"^zukan-[\d.]+\.apk$")
_CACHE_TTL = 3600
# A failed lookup (GitHub down, rate limit) is retried sooner.
_FAILURE_TTL = 300


class AndroidRelease(BaseModel):
    version: str
    # Direct download of the APK (github.com, redirects to its storage).
    url: str
    size: int
    published_at: datetime
    # Hex SHA-256 of the APK when GitHub gives one.
    sha256: str | None
    # Release page (changes).
    notes_url: str


_cache: tuple[float, str, AndroidRelease | None] | None = None


def clear_cache() -> None:
    global _cache
    _cache = None


def _pick(releases: list[dict]) -> AndroidRelease | None:
    candidates = []
    for release in releases:
        match = _TAG.match(release.get("tag_name") or "")
        if not match or release.get("draft") or release.get("prerelease"):
            continue
        apk = next((a for a in release.get("assets") or [] if _APK.match(a.get("name", ""))), None)
        if apk is None:
            continue
        digest = apk.get("digest") or ""
        candidates.append(
            (
                tuple(int(n) for n in match.groups()),
                AndroidRelease(
                    version=".".join(match.groups()),
                    url=apk["browser_download_url"],
                    size=apk.get("size") or 0,
                    published_at=release.get("published_at") or release.get("created_at"),
                    sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
                    notes_url=release.get("html_url") or "",
                ),
            )
        )
    return max(candidates, key=lambda c: c[0])[1] if candidates else None


async def latest_android() -> AndroidRelease | None:
    """Newest Android release, cached an hour; None when there is none, the feature is
    off (`TCG_ANDROID_RELEASE_REPO` empty) or GitHub cannot be reached."""
    global _cache
    repo = get_settings().android_release_repo.strip().strip("/")
    if not repo:
        return None
    if _cache is not None and _cache[1] == repo:
        at, _, release = _cache
        if time.monotonic() - at < (_CACHE_TTL if release else _FAILURE_TTL):
            return release
    release = None
    try:
        async with httpx.AsyncClient(
            timeout=15,
            headers={
                "User-Agent": get_settings().user_agent,
                "Accept": "application/vnd.github+json",
            },
        ) as http:
            response = await http.get(
                f"https://api.github.com/repos/{repo}/releases", params={"per_page": 50}
            )
            response.raise_for_status()
            release = _pick(response.json())
    except (httpx.HTTPError, ValueError):
        log.warning("Android release lookup on %s failed", repo, exc_info=True)
    _cache = (time.monotonic(), repo, release)
    return release
