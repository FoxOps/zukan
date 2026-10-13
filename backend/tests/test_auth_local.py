import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.main import create_default_admin
from app.models import Role, User
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

    # Reusing the rotated token is treated as theft: the whole family is revoked.
    reuse = await client.post("/api/auth/refresh", json={"refresh_token": first})
    assert reuse.status_code == 401
    after = await client.post("/api/auth/refresh", json={"refresh_token": second})
    assert after.status_code == 401


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


async def test_games_metadata(client, session):
    await make_user(session)
    headers = await bearer(client, "alice")
    games = {g["id"]: g for g in (await client.get("/api/games", headers=headers)).json()}
    assert set(games) == {"mtg", "pokemon", "sorcery"}
    assert [c["code"] for c in games["mtg"]["colors"]][:5] == ["W", "U", "B", "R", "G"]
    assert games["sorcery"]["has_prices"] is True
    assert (await client.get("/api/games")).status_code == 401
