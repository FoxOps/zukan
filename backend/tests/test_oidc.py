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
from app.core.oidc import get_auth_config
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


async def test_link_sso_to_local_account(client, session, idp):
    await make_user(session)
    login = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "password123", "mode": "cookie"},
        headers=CSRF,
    )
    assert login.status_code == 200
    query = await start_login(client, link="true")
    await finish_login(client, idp, query)
    me = (await client.get("/api/auth/me")).json()
    assert me["username"] == "alice"
    assert len(me["identities"]) == 1

    # Unlinking works because the account still has a password.
    identity_id = me["identities"][0]["id"]
    response = await client.delete(f"/api/auth/identities/{identity_id}", headers=CSRF)
    assert response.status_code == 204


async def test_link_requires_login(client, idp):
    response = await client.get("/api/auth/oidc/home/login", params={"link": "true"})
    assert response.status_code == 401


async def test_cannot_unlink_last_login_method(client, idp):
    query = await start_login(client)
    await finish_login(client, idp, query)
    me = (await client.get("/api/auth/me")).json()
    response = await client.delete(
        f"/api/auth/identities/{me['identities'][0]['id']}", headers=CSRF
    )
    assert response.status_code == 400


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
