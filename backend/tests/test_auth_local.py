from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.main import create_default_admin
from app.models import RefreshToken, Role, User
from tests.conftest import CSRF, bearer, make_user


@pytest.mark.smoke
async def test_login_token_mode_and_me(client, session):
    await make_user(session)
    headers = await bearer(client, "alice")
    response = await client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "alice"
    assert body["has_password"] is True
    assert body["identities"] == []


@pytest.mark.smoke
async def test_default_admin_created_on_empty_database(client, session):
    await create_default_admin()
    await create_default_admin()  # idempotent across restarts
    assert await session.scalar(select(func.count()).select_from(User)) == 1
    headers = await bearer(client, "admin", "changeme")
    me = (await client.get("/api/auth/me", headers=headers)).json()
    assert me["role"] == "admin"
    # The default password can be changed like any other.
    response = await client.post(
        "/api/auth/password",
        json={"current_password": "changeme", "new_password": "a-better-password"},
        headers=headers,
    )
    assert response.status_code == 204
    await create_default_admin()
    await bearer(client, "admin", "a-better-password")


async def test_default_admin_not_created_when_users_exist(session):
    await make_user(session)
    await create_default_admin()
    usernames = await session.scalars(select(User.username))
    assert list(usernames) == ["alice"]


async def test_default_admin_settings(client, session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "default_admin_password", "")
    await create_default_admin()
    assert await session.scalar(select(func.count()).select_from(User)) == 0

    monkeypatch.setattr(settings, "default_admin_username", "root")
    monkeypatch.setattr(settings, "default_admin_password", "custom-password")
    await create_default_admin()
    await bearer(client, "root", "custom-password")


async def test_login_rejects_bad_password_unknown_and_disabled(client, session):
    await make_user(session)
    await make_user(session, "bob", disabled=True)
    for username, password in [
        ("alice", "wrong-pass"),
        ("nobody", "password123"),
        ("bob", "password123"),
    ]:
        response = await client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 401


async def test_sso_only_user_cannot_login_locally(client, session):
    await make_user(session, password=None)
    response = await client.post("/api/auth/login", json={"username": "alice", "password": ""})
    assert response.status_code == 401


async def test_local_login_can_be_disabled(client, session):
    await make_user(session)
    get_settings().local_login_enabled = False
    response = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "password123"}
    )
    assert response.status_code == 403
    assert (await client.get("/api/auth/providers")).json()["local_login_enabled"] is False


@pytest.mark.smoke
async def test_refresh_rotates_and_detects_reuse(client, session):
    await make_user(session)
    login = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "password123"}
    )
    first = login.json()["refresh_token"]

    rotated = await client.post("/api/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first

    # Reusing it right away (another tab refreshing at the same time) is accepted.
    again = await client.post("/api/auth/refresh", json={"refresh_token": first})
    assert again.status_code == 200

    # Past the grace period, reuse is treated as theft: the whole family is revoked.
    await session.execute(
        update(RefreshToken).values(rotated_at=RefreshToken.rotated_at - timedelta(minutes=5))
    )
    await session.commit()
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": first})
    assert reuse.status_code == 401
    after = await client.post("/api/auth/refresh", json={"refresh_token": second})
    assert after.status_code == 401


async def test_rotated_token_refused_after_logout(client, session):
    await make_user(session)
    login = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "password123"}
    )
    first = login.json()["refresh_token"]
    second = (await client.post("/api/auth/refresh", json={"refresh_token": first})).json()[
        "refresh_token"
    ]
    assert (
        await client.post("/api/auth/logout", json={"refresh_token": second})
    ).status_code == 200
    # Even within the grace period, a logged-out session does not come back.
    assert (
        await client.post("/api/auth/refresh", json={"refresh_token": first})
    ).status_code == 401


async def test_logout_revokes_refresh_token(client, session):
    await make_user(session)
    login = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "password123"}
    )
    token = login.json()["refresh_token"]
    assert (await client.post("/api/auth/logout", json={"refresh_token": token})).status_code == 200
    assert (
        await client.post("/api/auth/refresh", json={"refresh_token": token})
    ).status_code == 401


@pytest.mark.smoke
async def test_cookie_mode_requires_csrf_header(client, session):
    await make_user(session)
    body = {"username": "alice", "password": "password123", "mode": "cookie"}
    assert (await client.post("/api/auth/login", json=body)).status_code == 403

    response = await client.post("/api/auth/login", json=body, headers=CSRF)
    assert response.status_code == 200
    assert "access_token" not in response.json()
    assert "tcg_access" in client.cookies

    assert (await client.get("/api/auth/me")).status_code == 200
    # Cookie-authenticated write without the header is refused.
    change = {"current_password": "password123", "new_password": "newpassword1"}
    assert (await client.post("/api/auth/password", json=change)).status_code == 403
    assert (await client.post("/api/auth/password", json=change, headers=CSRF)).status_code == 204

    refreshed = await client.post("/api/auth/refresh", json={}, headers=CSRF)
    assert refreshed.status_code == 200
    logout = await client.post("/api/auth/logout", json={}, headers=CSRF)
    assert logout.status_code == 200
    assert "tcg_access" not in client.cookies


async def test_password_change_requires_current_password(client, session):
    await make_user(session)
    headers = await bearer(client, "alice")
    bad = {"current_password": "nope", "new_password": "newpassword1"}
    assert (await client.post("/api/auth/password", json=bad, headers=headers)).status_code == 400


async def test_admin_user_management(client, session):
    await make_user(session, "root", role=Role.admin)
    await make_user(session)
    admin = await bearer(client, "root")
    user = await bearer(client, "alice")

    assert (await client.get("/api/users", headers=user)).status_code == 403

    created = await client.post(
        "/api/users", json={"username": "carol", "password": "password123"}, headers=admin
    )
    assert created.status_code == 201
    carol_id = created.json()["id"]
    duplicate = await client.post("/api/users", json={"username": "carol"}, headers=admin)
    assert duplicate.status_code == 409

    disabled = await client.patch(f"/api/users/{carol_id}", json={"disabled": True}, headers=admin)
    assert disabled.json()["disabled"] is True
    login = await client.post(
        "/api/auth/login", json={"username": "carol", "password": "password123"}
    )
    assert login.status_code == 401

    me = (await client.get("/api/auth/me", headers=admin)).json()
    assert (await client.delete(f"/api/users/{me['id']}", headers=admin)).status_code == 400
    demote = await client.patch(f"/api/users/{me['id']}", json={"role": "user"}, headers=admin)
    assert demote.status_code == 400
    assert (await client.delete(f"/api/users/{carol_id}", headers=admin)).status_code == 204


@pytest.mark.gap_sources
async def test_games_metadata(client, session):
    await make_user(session)
    headers = await bearer(client, "alice")
    games = {g["id"]: g for g in (await client.get("/api/games", headers=headers)).json()}
    assert set(games) == {"mtg", "pokemon", "sorcery", "riftbound", "yugioh", "lorcana"}
    assert [r["code"] for r in games["lorcana"]["rarities"]][:3] == ["common", "uncommon", "rare"]
    assert games["yugioh"]["finishes"][1] == {"code": "first", "name": "1st Edition"}
    assert [c["code"] for c in games["mtg"]["colors"]][:5] == ["W", "U", "B", "R", "G"]
    assert games["sorcery"]["has_prices"] is True
    # tcgcsv prices Sorcery and Riftbound on TCGplayer.
    assert [s["id"] for s in games["sorcery"]["price_sources"]] == ["cardmarket", "tcgplayer"]
    assert games["riftbound"]["legal_notice"].startswith("Zukan isn't endorsed by Riot Games")
    assert all(g["legal_notice"] for g in games.values())
    assert games["mtg"]["legal_notice"].startswith("Zukan is unofficial Fan Content")
    assert (await client.get("/api/games")).status_code == 401


async def test_change_own_email(client, session):
    await make_user(session)
    headers = await bearer(client, "alice")
    wrong = await client.post(
        "/api/auth/email",
        json={"email": "a@example.org", "current_password": "nope"},
        headers=headers,
    )
    assert wrong.status_code == 400
    bad = await client.post(
        "/api/auth/email",
        json={"email": "not an email", "current_password": "password123"},
        headers=headers,
    )
    assert bad.status_code == 422
    done = await client.post(
        "/api/auth/email",
        json={"email": "a@example.org", "current_password": "password123"},
        headers=headers,
    )
    assert done.status_code == 200 and done.json()["email"] == "a@example.org"
    cleared = await client.post(
        "/api/auth/email", json={"email": None, "current_password": "password123"}, headers=headers
    )
    assert cleared.json()["email"] is None


async def _login(client, username="alice", password="password123"):
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["refresh_token"]


async def _refresh(client, token):
    return (await client.post("/api/auth/refresh", json={"refresh_token": token})).status_code


async def test_password_change_ends_every_session(client, session):
    await make_user(session)
    await make_user(session, "bob")
    access, refresh = await _login(client)
    other_access, other_refresh = await _login(client)
    bob, _ = await _login(client, "bob")
    change = {"current_password": "password123", "new_password": "newpassword1"}
    assert (await client.post("/api/auth/password", json=change, headers=access)).status_code == 204
    for headers in (access, other_access):
        assert (await client.get("/api/auth/me", headers=headers)).status_code == 401
    assert await _refresh(client, refresh) == 401
    assert await _refresh(client, other_refresh) == 401
    # Other accounts keep their sessions; only the new password signs in.
    assert (await client.get("/api/auth/me", headers=bob)).status_code == 200
    old = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "password123"}
    )
    assert old.status_code == 401
    new, _ = await _login(client, password="newpassword1")
    assert (await client.get("/api/auth/me", headers=new)).status_code == 200


async def test_browser_keeps_its_session_after_password_change(client, session):
    await make_user(session)
    body = {"username": "alice", "password": "password123", "mode": "cookie"}
    assert (await client.post("/api/auth/login", json=body, headers=CSRF)).status_code == 200
    old_refresh = client.cookies["tcg_refresh"]
    change = {"current_password": "password123", "new_password": "newpassword1"}
    assert (await client.post("/api/auth/password", json=change, headers=CSRF)).status_code == 204
    # New cookies: still signed in, the previous refresh token is dead.
    assert client.cookies["tcg_refresh"] != old_refresh
    assert (await client.get("/api/auth/me")).status_code == 200
    assert await _refresh(client, old_refresh) == 401


async def test_admin_reset_and_disable_end_sessions(client, session):
    await make_user(session, "root", role=Role.admin)
    alice = await make_user(session)
    admin = await bearer(client, "root")
    access, refresh = await _login(client)
    reset = await client.patch(
        f"/api/users/{alice.id}", json={"password": "resetpass12"}, headers=admin
    )
    assert reset.status_code == 200
    assert (await client.get("/api/auth/me", headers=access)).status_code == 401
    assert await _refresh(client, refresh) == 401

    access, refresh = await _login(client, password="resetpass12")
    url = f"/api/users/{alice.id}"
    assert (await client.patch(url, json={"disabled": True}, headers=admin)).status_code == 200
    assert (await client.patch(url, json={"disabled": False}, headers=admin)).status_code == 200
    # Enabled again, the sessions from before stay ended.
    assert (await client.get("/api/auth/me", headers=access)).status_code == 401
    assert await _refresh(client, refresh) == 401
    # Other changes (role, email) keep them.
    access, refresh = await _login(client, password="resetpass12")
    assert (await client.patch(url, json={"email": "a@b.c"}, headers=admin)).status_code == 200
    assert (await client.get("/api/auth/me", headers=access)).status_code == 200


async def test_logout_ends_access_token_of_that_session_only(client, session):
    await make_user(session)
    access, refresh = await _login(client)
    other, _ = await _login(client)
    assert (
        await client.post("/api/auth/logout", json={"refresh_token": refresh})
    ).status_code == 200
    assert (await client.get("/api/auth/me", headers=access)).status_code == 401
    assert (await client.get("/api/auth/me", headers=other)).status_code == 200


async def test_token_without_session_refused(client, session):
    from app.core.security import sign

    user = await make_user(session)
    # Shape of access tokens before 0.14.0.
    token = sign({"sub": str(user.id), "role": "user"}, timedelta(minutes=5), "access")
    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_failed_logins_are_rate_limited(client, session, monkeypatch):
    from app.core import ratelimit

    now = [1000.0]
    for counter in (ratelimit.failed_by_name, ratelimit.failed_by_address):
        monkeypatch.setattr(counter, "clock", lambda: now[0])
    settings = get_settings()
    monkeypatch.setattr(settings, "login_max_failures", 3)
    monkeypatch.setattr(settings, "login_ip_max_failures", 5)
    await make_user(session)
    await make_user(session, "bob")
    wrong = {"username": "alice", "password": "wrong-password"}
    for _ in range(3):
        assert (await client.post("/api/auth/login", json=wrong)).status_code == 401
    # Blocked, even with the right password, for the rest of the window.
    blocked = await client.post(
        "/api/auth/login", json={"username": "Alice ", "password": "password123"}
    )
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    # Another account from the same address still signs in.
    await bearer(client, "bob")
    # A forwarded address from a client that is not a trusted proxy changes nothing.
    spoofed = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "password123"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert spoofed.status_code == 429
    now[0] += settings.login_window_seconds + 1
    await bearer(client, "alice")
    # Too many failures from one address, whatever the account.
    for name in ("x1", "x2", "x3", "x4", "x5"):
        bad = {"username": name, "password": "nope-nope"}
        assert (await client.post("/api/auth/login", json=bad)).status_code == 401
    refused = await client.post(
        "/api/auth/login", json={"username": "bob", "password": "password123"}
    )
    assert refused.status_code == 429


async def test_refresh_requests_capped_per_address(client, session, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_requests_per_minute", 2)
    for _ in range(2):
        response = await client.post("/api/auth/refresh", json={"refresh_token": "x"})
        assert response.status_code == 401
    response = await client.post("/api/auth/refresh", json={"refresh_token": "x"})
    assert response.status_code == 429
