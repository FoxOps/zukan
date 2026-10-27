"""Latest Android app from GitHub releases (web download, app update check)."""

import httpx
import pytest
import respx

from app.core.config import get_settings
from app.services import app_release
from tests.conftest import bearer, make_user

RELEASES = "https://api.github.com/repos/FoxOps/zukan/releases"


def release(tag: str, assets: list[str], prerelease: bool = False) -> dict:
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": prerelease,
        "published_at": "2026-10-27T10:00:00Z",
        "html_url": f"https://github.com/FoxOps/zukan/releases/tag/{tag}",
        "assets": [
            {
                "name": name,
                "size": 24_000_000,
                "browser_download_url": f"https://github.com/dl/{name}",
                "digest": "sha256:" + "ab" * 32,
            }
            for name in assets
        ],
    }


@pytest.fixture(autouse=True)
def fresh_cache():
    app_release.clear_cache()
    yield
    app_release.clear_cache()


async def test_latest_android_release(client, session):
    await make_user(session)
    headers = await bearer(client, "alice")
    with respx.mock(assert_all_called=False) as router:
        route = router.get(RELEASES).respond(
            json=[
                release("server-v0.19.0", []),  # newest is a server release
                release("android-dev-branch", ["zukan-dev-branch-abc.apk"], prerelease=True),
                release("android-v0.12.0", ["zukan-0.12.0.apk"], prerelease=True),
                release("android-v0.11.0", ["mapping-0.11.0.txt", "zukan-0.11.0.apk"]),
                release("android-v0.9.0", ["zukan-0.9.0.apk"]),
                release("android-v0.10.0", ["mapping-0.10.0.txt"]),  # no APK
            ]
        )
        body = (await client.get("/api/app/android", headers=headers)).json()
        assert body["version"] == "0.11.0"
        assert body["url"] == "https://github.com/dl/zukan-0.11.0.apk"
        assert body["sha256"] == "ab" * 32 and body["size"] == 24_000_000
        assert body["notes_url"].endswith("android-v0.11.0")
        # Cached: GitHub asked once.
        await client.get("/api/app/android", headers=headers)
        assert route.call_count == 1

    assert (await client.get("/api/app/android")).status_code == 401


async def test_no_release_or_github_down(client, session, monkeypatch):
    await make_user(session)
    headers = await bearer(client, "alice")
    with respx.mock(assert_all_called=False) as router:
        router.get(RELEASES).mock(side_effect=httpx.ConnectError("down"))
        assert (await client.get("/api/app/android", headers=headers)).status_code == 404
    monkeypatch.setattr(get_settings(), "android_release_repo", "")
    app_release.clear_cache()
    assert await app_release.latest_android() is None
