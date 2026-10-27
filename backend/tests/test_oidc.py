import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings, get_settings
from app.core.oidc import get_auth_config, guess_account_url
from app.models import Role
from tests.conftest import CSRF, bearer, make_user

ISSUER = "https://idp.test/realms/home"
WEB_CLIENT = "tcg-web"
MOBILE_CLIENT = "tcg-android"


class FakeIdp:
    """Minimal OIDC provider: discovery, JWKS, token and userinfo endpoints."""

    def __init__(self, router: respx.Router):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "key-1"
        self.next_claims: dict = {}
        self.userinfo: dict = {}
        self.token_requests: list[httpx.Request] = []
        router.get(f"{ISSUER}/.well-known/openid-configuration").respond(
            json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/auth",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/certs",
                "userinfo_endpoint": f"{ISSUER}/userinfo",
                "end_session_endpoint": f"{ISSUER}/logout",
            }
        )
        router.get(f"{ISSUER}/certs").mock(side_effect=self._jwks)
        router.post(f"{ISSUER}/token").mock(side_effect=self._token)
        router.get(f"{ISSUER}/userinfo").mock(
            side_effect=lambda _: httpx.Response(200, json=self.userinfo)
        )

    def _jwks(self, _request) -> httpx.Response:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update(kid=self.kid, use="sig", alg="RS256")
        return httpx.Response(200, json={"keys": [jwk]})

    def _token(self, request) -> httpx.Response:
        self.token_requests.append(request)
        return httpx.Response(
            200, json={"id_token": self.id_token(**self.next_claims), "access_token": "at"}
        )

    def id_token(self, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "sub": "subject-1",
            "aud": WEB_CLIENT,
            "iat": now,
            "exp": now + 300,
            "preferred_username": "sso.alice",
            "email": "alice@example.com",
            "groups": ["tcg-users"],
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})


def configure(monkeypatch, **provider_overrides) -> None:
    provider = {
        "display_name": "Home SSO",
        "issuer": ISSUER,
        "client_id": WEB_CLIENT,
        "client_secret": "s3cret",
        "mobile_client_id": MOBILE_CLIENT,
        "scopes": ["openid", "profile", "email", "groups"],
        "admin_groups": ["tcg-admins"],
        **provider_overrides,
    }
    for key, value in provider.items():
        value = value if isinstance(value, str) else json.dumps(value)
        monkeypatch.setenv(f"TCG_OIDC_HOME_{key.upper()}", value)
    monkeypatch.setattr(get_settings(), "oidc_providers", ["home"])
    get_auth_config.cache_clear()


@pytest.fixture
def idp(monkeypatch):
    configure(monkeypatch)
    with respx.mock(assert_all_called=False) as router:
        yield FakeIdp(router)


async def start_login(client, path="/api/auth/oidc/home/login", **params) -> dict:
    response = await client.get(path, params=params)
    assert response.status_code == 302, response.text
    url = urlparse(response.headers["location"])
    assert url.netloc == "idp.test"
    return {k: v[0] for k, v in parse_qs(url.query).items()}


async def finish_login(client, idp, query, **claims) -> httpx.Response:
    idp.next_claims = {"nonce": query["nonce"], **claims}
    return await client.get(
        "/api/auth/oidc/home/callback", params={"code": "abc", "state": query["state"]}
    )


async def test_providers_listing(client, idp):
    body = (await client.get("/api/auth/providers")).json()
    assert body["providers"] == [
        {
            "name": "home",
            "display_name": "Home SSO",
            "issuer": ISSUER,
            "mobile_client_id": MOBILE_CLIENT,
            "scopes": ["openid", "profile", "email", "groups"],
            # Guessed from the Keycloak issuer.
            "account_url": f"{ISSUER}/account",
        }
    ]


@pytest.mark.smoke
async def test_web_login_creates_user(client, idp):
    query = await start_login(client, next="/collection")
    assert query["client_id"] == WEB_CLIENT
    assert query["code_challenge_method"] == "S256"
    assert query["redirect_uri"] == "http://testserver/api/auth/oidc/home/callback"

    response = await finish_login(client, idp, query)
    assert response.status_code == 303
    assert response.headers["location"] == "/collection"

    token_request = idp.token_requests[0]
    form = parse_qs(token_request.content.decode())
    assert form["code_verifier"][0]
    assert token_request.headers["authorization"].startswith("Basic ")

    me = (await client.get("/api/auth/me")).json()
    assert me["username"] == "sso.alice"
    assert me["role"] == "user"
    assert me["has_password"] is False
    assert [i["provider"] for i in me["identities"]] == ["home"]

    # Same subject logs into same account.
    client.cookies.clear()
    query = await start_login(client)
    await finish_login(client, idp, query)
    assert (await client.get("/api/auth/me")).json()["id"] == me["id"]


async def test_admin_group_maps_role(client, idp):
    query = await start_login(client)
    await finish_login(client, idp, query, groups=["tcg-admins"])
    assert (await client.get("/api/auth/me")).json()["role"] == "admin"

    # Role follows the IdP on next login.
    client.cookies.clear()
    query = await start_login(client)
    await finish_login(client, idp, query, groups=[])
    assert (await client.get("/api/auth/me")).json()["role"] == "user"


async def test_role_of_sso_users_set_by_idp_is_locked(client, session, idp, monkeypatch):
    query = await start_login(client)
    await finish_login(client, idp, query)
    sso_id = (await client.get("/api/auth/me")).json()["id"]
    await make_user(session, "root", role=Role.admin)
    await make_user(session, "bob")
    admin = {**await bearer(client, "root"), **CSRF}
    users = {u["username"]: u for u in (await client.get("/api/users", headers=admin)).json()}
    assert users["sso.alice"]["role_managed_by_sso"] is True
    assert users["bob"]["role_managed_by_sso"] is False

    # The IdP's admin groups set the role at every login: no change here.
    response = await client.patch(f"/api/users/{sso_id}", json={"role": "admin"}, headers=admin)
    assert response.status_code == 409 and "role" in response.json()["detail"]
    unchanged = {"role": "user", "disabled": True}
    response = await client.patch(f"/api/users/{sso_id}", json=unchanged, headers=admin)
    assert response.status_code == 200 and response.json()["role_managed_by_sso"]
    bob_id = users["bob"]["id"]
    response = await client.patch(f"/api/users/{bob_id}", json={"role": "admin"}, headers=admin)
    assert response.status_code == 200

    # Without admin groups, the IdP leaves roles to Zukan's administrators.
    configure(monkeypatch, admin_groups=[])
    users = {u["username"]: u for u in (await client.get("/api/users", headers=admin)).json()}
    assert users["sso.alice"]["sso"] and not users["sso.alice"]["role_managed_by_sso"]
    response = await client.patch(f"/api/users/{sso_id}", json={"role": "admin"}, headers=admin)
    assert response.status_code == 200 and response.json()["role"] == "admin"


async def test_no_local_users_created_when_local_login_disabled(client, session, monkeypatch):
    await make_user(session, "root", role=Role.admin)
    admin = {**await bearer(client, "root"), **CSRF}
    monkeypatch.setattr(get_settings(), "local_login_enabled", False)
    response = await client.post("/api/users", json={"username": "bob"}, headers=admin)
    assert response.status_code == 403


async def test_no_account_linking_by_email(client, idp):
    query = await start_login(client)
    await finish_login(client, idp, query)
    first = (await client.get("/api/auth/me")).json()

    client.cookies.clear()
    query = await start_login(client)
    await finish_login(client, idp, query, sub="other-subject")
    second = (await client.get("/api/auth/me")).json()
    assert second["id"] != first["id"]
    assert second["username"] == "sso.alice-2"


@pytest.mark.parametrize(
    ("claims", "error"),
    [
        ({"nonce": "forged"}, "Invalid SSO token"),
        ({"aud": "someone-else"}, "Invalid SSO token"),
        ({"iss": "https://evil.test"}, "Invalid SSO token"),
        ({"exp": int(time.time()) - 600}, "Invalid SSO token"),
    ],
)
async def test_invalid_id_tokens_rejected(client, idp, claims, error):
    query = await start_login(client)
    idp.next_claims = {"nonce": query["nonce"], **claims}
    response = await client.get(
        "/api/auth/oidc/home/callback", params={"code": "abc", "state": query["state"]}
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?error=")
    assert error.replace(" ", "%20") in response.headers["location"]
    assert "tcg_access" not in client.cookies


async def test_token_signed_by_other_key_rejected(client, idp):
    query = await start_login(client)
    idp.next_claims = {"nonce": query["nonce"]}
    good_key = idp.key
    # Token endpoint signs with a key absent from JWKS (same kid).
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    original = idp.id_token
    idp.id_token = lambda **kw: (
        setattr(idp, "key", attacker),
        original(**kw),
        setattr(idp, "key", good_key),
    )[1]
    response = await client.get(
        "/api/auth/oidc/home/callback", params={"code": "abc", "state": query["state"]}
    )
    assert response.headers["location"].startswith("/login?error=")


async def test_state_mismatch_and_missing_cookie(client, idp):
    query = await start_login(client)
    response = await client.get(
        "/api/auth/oidc/home/callback", params={"code": "abc", "state": "wrong"}
    )
    assert response.headers["location"].startswith("/login?error=Invalid%20SSO%20response")

    client.cookies.clear()
    response = await client.get(
        "/api/auth/oidc/home/callback", params={"code": "abc", "state": query["state"]}
    )
    assert "expired" in response.headers["location"]


async def test_idp_error_and_open_redirect(client, idp):
    response = await client.get("/api/auth/oidc/home/callback", params={"error": "access_denied"})
    assert response.headers["location"] == "/login?error=access_denied"

    query = await start_login(client, next="//evil.test/")
    response = await finish_login(client, idp, query)
    assert response.headers["location"] == "/"


async def test_allowed_groups_and_auto_create(client, idp, monkeypatch):
    configure(monkeypatch, allowed_groups=["tcg-users"])
    query = await start_login(client)
    response = await finish_login(client, idp, query, groups=["other"])
    assert "not%20allowed" in response.headers["location"]

    configure(monkeypatch, auto_create_users=False)
    query = await start_login(client)
    response = await finish_login(client, idp, query)
    assert "No%20account" in response.headers["location"]


async def test_groups_from_userinfo(client, idp):
    idp.userinfo = {"sub": "subject-1", "groups": ["tcg-admins"]}
    query = await start_login(client)
    await finish_login(client, idp, query, groups=None)
    assert (await client.get("/api/auth/me")).json()["role"] == "admin"


async def test_sso_never_joins_local_account(client, session, idp):
    """SSO and local accounts are separate: a signed-in local user going through SSO gets
    the SSO account, not an identity on the local one."""
    await make_user(session, "alice")
    login = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "password123", "mode": "cookie"},
        headers=CSRF,
    )
    assert login.status_code == 200
    query = await start_login(client, link="true")
    await finish_login(client, idp, query)
    me = (await client.get("/api/auth/me")).json()
    assert me["username"] == "sso.alice" and me["sso"] is True
    local = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "password123", "mode": "token"},
    )
    assert local.status_code == 200
    alice = (await client.get("/api/auth/me", headers=await bearer(client, "alice"))).json()
    assert alice["identities"] == [] and alice["sso"] is False
    # No unlink: identities stay with their SSO account.
    response = await client.delete(f"/api/auth/identities/{me['identities'][0]['id']}")
    assert response.status_code in (404, 405)


async def test_sso_email_shown_on_account(client, session, idp):
    """The IdP's email reaches the account on creation and later logins, verified or
    not, from the ID token or userinfo; the admin list shows it too."""
    query = await start_login(client)
    await finish_login(client, idp, query, email_verified=False)
    me = (await client.get("/api/auth/me")).json()
    assert me["email"] == "alice@example.com" and me["sso"] is True
    assert me["sso_account"] == {
        "provider": "home",
        "display_name": "Home SSO",
        "account_url": f"{ISSUER}/account",
    }

    # Changed at the IdP: copied on the next login. Only in userinfo: fetched there.
    idp.userinfo = {"sub": "subject-1", "email": "alice@new.example"}
    client.cookies.clear()
    query = await start_login(client)
    await finish_login(client, idp, query, email=None)
    assert (await client.get("/api/auth/me")).json()["email"] == "alice@new.example"

    await make_user(session, "root", role=Role.admin)
    users = (await client.get("/api/users", headers=await bearer(client, "root"))).json()
    by_name = {u["username"]: u for u in users}
    assert by_name["sso.alice"]["email"] == "alice@new.example" and by_name["sso.alice"]["sso"]
    assert by_name["root"]["sso"] is False


async def test_sso_users_change_password_and_email_at_idp(client, session, idp):
    # Administrators too: SSO accounts never get a local password.
    query = await start_login(client)
    await finish_login(client, idp, query, groups=["tcg-admins"])
    email = await client.post("/api/auth/email", json={"email": "x@example.com"}, headers=CSRF)
    assert email.status_code == 409
    password = await client.post(
        "/api/auth/password", json={"new_password": "password123"}, headers=CSRF
    )
    assert password.status_code == 409
    me = (await client.get("/api/auth/me")).json()
    for body in ({"email": "x@example.com"}, {"password": "password123"}):
        response = await client.patch(f"/api/users/{me['id']}", json=body, headers=CSRF)
        assert response.status_code == 409


def test_account_url_guessed_from_issuer():
    assert guess_account_url("https://kc.example/realms/home") == (
        "https://kc.example/realms/home/account"
    )
    assert guess_account_url("https://ak.example/application/o/zukan/") == (
        "https://ak.example/if/user/#/settings"
    )
    assert guess_account_url("https://auth.example") is None


@pytest.mark.smoke
async def test_mobile_exchange(client, idp):
    token = idp.id_token(aud=MOBILE_CLIENT, nonce="n1")
    response = await client.post(
        "/api/auth/oidc/home/exchange", json={"id_token": token, "nonce": "n1"}
    )
    assert response.status_code == 200, response.text
    tokens = response.json()
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.json()["username"] == "sso.alice"


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": WEB_CLIENT, "nonce": "n1"},  # web client token not accepted
        {"aud": MOBILE_CLIENT, "nonce": "other"},
        {"aud": MOBILE_CLIENT, "nonce": "n1", "iat": int(time.time()) - 3600},
    ],
)
async def test_mobile_exchange_rejections(client, idp, overrides):
    token = idp.id_token(**overrides)
    response = await client.post(
        "/api/auth/oidc/home/exchange", json={"id_token": token, "nonce": "n1"}
    )
    assert response.status_code == 401


async def test_key_rotation_refetches_jwks(client, idp):
    query = await start_login(client)
    await finish_login(client, idp, query)
    idp.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    idp.kid = "key-2"
    client.cookies.clear()
    query = await start_login(client)
    response = await finish_login(client, idp, query)
    assert response.headers["location"] == "/"


async def test_logout_returns_end_session_url(client, idp):
    query = await start_login(client)
    await finish_login(client, idp, query)
    body = (await client.post("/api/auth/logout", json={}, headers=CSRF)).json()
    assert body["end_session_url"].startswith(f"{ISSUER}/logout?client_id=tcg-web")


async def test_unknown_provider(client, idp):
    assert (await client.get("/api/auth/oidc/nope/login")).status_code == 404


async def test_bearer_still_works_alongside_sso(client, session, idp):
    await make_user(session)
    headers = await bearer(client, "alice")
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 200


def test_provider_settings_errors_and_defaults(monkeypatch):
    monkeypatch.setattr(get_settings(), "oidc_providers", ["my-idp"])
    monkeypatch.setenv("TCG_OIDC_MY_IDP_ISSUER", ISSUER)
    with pytest.raises(ValueError, match="TCG_OIDC_MY_IDP_CLIENT_ID"):
        get_auth_config()

    monkeypatch.setenv("TCG_OIDC_MY_IDP_CLIENT_ID", WEB_CLIENT)
    get_auth_config.cache_clear()
    (provider,) = get_auth_config().providers
    assert provider.name == "my-idp"
    assert provider.display_name == "my-idp"
    assert provider.scopes == ["openid", "profile", "email"]
    assert provider.auto_create_users is True


def test_env_example_sso_section_is_valid(monkeypatch):
    # Uncommenting the SSO example of .env.example gives a working configuration.
    example = (Path(__file__).parents[2] / ".env.example").read_text()
    for line in example.splitlines():
        if line.startswith("# TCG_OIDC_"):
            key, _, value = line.removeprefix("# ").partition("=")
            monkeypatch.setenv(key, value)
    providers = Settings().oidc_providers
    monkeypatch.setattr(get_settings(), "oidc_providers", providers)
    (provider,) = get_auth_config().providers
    assert provider.name == "home"
    assert provider.mobile_client_id == "tcg-android"


async def test_unreachable_idp_is_a_login_error(client, monkeypatch):
    """The login page sends SSO-only users straight to the IdP: an IdP that cannot be
    reached must bring them back with a message, not a server error."""
    configure(monkeypatch)
    with respx.mock() as router:
        router.get(f"{ISSUER}/.well-known/openid-configuration").mock(
            side_effect=httpx.ConnectError("down")
        )
        response = await client.get("/api/auth/oidc/home/login")
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?error=")
