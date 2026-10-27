"""Generic OpenID Connect relying party.

Only standard OIDC is used (discovery, authorization code + PKCE, JWKS), so any compliant
IdP works: Keycloak, Authentik, Authelia, Zitadel, Google...
"""

import base64
import hashlib
import re
import secrets
import time
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import get_settings

# Asymmetric algorithms only: HS* would require trusting the client secret as a key.
ALLOWED_ALGORITHMS = [
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
]
_CACHE_TTL = 3600
_CLOCK_LEEWAY = 60


class OidcError(Exception):
    """Login refused or IdP response invalid. Message is safe to show to the user."""


class OidcProviderConfig(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    display_name: str
    issuer: str
    client_id: str
    client_secret: str | None = None
    # Public client used by the Android app (AppAuth + PKCE). Its ID tokens are
    # accepted by the exchange endpoint.
    mobile_client_id: str | None = None
    scopes: list[str] = ["openid", "profile", "email"]
    username_claim: str = "preferred_username"
    groups_claim: str = "groups"
    # When set, role is synced from groups on every SSO login.
    admin_groups: list[str] = []
    # When set, users outside these groups are refused.
    allowed_groups: list[str] = []
    auto_create_users: bool = True
    # Page where users change their password and email at the IdP (None: unknown).
    account_url: str | None = None


class _ProviderSettings(BaseSettings):
    """One provider's TCG_OIDC_<NAME>_* variables (prefix given on instantiation)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    display_name: str | None = None
    issuer: str
    client_id: str
    client_secret: str | None = None
    mobile_client_id: str | None = None
    scopes: list[str] = ["openid", "profile", "email"]
    username_claim: str = "preferred_username"
    groups_claim: str = "groups"
    admin_groups: list[str] = []
    allowed_groups: list[str] = []
    auto_create_users: bool = True
    account_url: str | None = None


def env_prefix(name: str) -> str:
    return f"TCG_OIDC_{name.upper().replace('-', '_')}_"


class AuthConfig(BaseModel):
    providers: list[OidcProviderConfig] = []


@lru_cache
def get_auth_config() -> AuthConfig:
    """Providers listed in TCG_OIDC_PROVIDERS, each configured by TCG_OIDC_<NAME>_*."""
    providers = []
    for name in get_settings().oidc_providers:
        try:
            values = _ProviderSettings(_env_prefix=env_prefix(name))
        except ValidationError as exc:
            missing = ", ".join(env_prefix(name) + str(e["loc"][0]).upper() for e in exc.errors())
            raise ValueError(f"SSO provider {name!r}: invalid or missing {missing}") from exc
        data = values.model_dump()
        data["display_name"] = data["display_name"] or name
        data["account_url"] = data["account_url"] or guess_account_url(data["issuer"])
        providers.append(OidcProviderConfig(name=name, **data))
    return AuthConfig(providers=providers)


def guess_account_url(issuer: str) -> str | None:
    """Account page of IdPs whose issuer tells them apart: Keycloak
    (`https://host/realms/<realm>`) and Authentik (`https://host/application/o/<slug>/`).
    Others need TCG_OIDC_<NAME>_ACCOUNT_URL."""
    parts = urlsplit(issuer)
    path = parts.path.rstrip("/")
    if re.search(r"/realms/[^/]+$", path):
        return f"{issuer.rstrip('/')}/account"
    if "/application/o/" in f"{path}/":
        return f"{parts.scheme}://{parts.netloc}/if/user/#/settings"
    return None


def local_login_enabled() -> bool:
    return get_settings().local_login_enabled


def get_provider(name: str) -> OidcProviderConfig:
    for provider in get_auth_config().providers:
        if provider.name == name:
            return provider
    raise OidcError(f"Unknown SSO provider {name!r}")


def redirect_uri(provider: OidcProviderConfig) -> str:
    return f"{get_settings().public_url.rstrip('/')}/api/auth/oidc/{provider.name}/callback"


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def extract_groups(claims: dict[str, Any], claim: str) -> set[str]:
    value = claims.get(claim)
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(v) for v in value}
    return set()


class OidcClient:
    def __init__(self, config: OidcProviderConfig):
        self.config = config
        self._metadata: dict[str, Any] | None = None
        self._metadata_at = 0.0
        self._jwks: jwt.PyJWKSet | None = None
        self._jwks_at = 0.0

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=10, headers={"User-Agent": get_settings().user_agent})

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """IdP request; network errors become a login error, not a server error."""
        try:
            async with self._http() as http:
                return await http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise OidcError("SSO provider unreachable, try again later") from exc

    async def metadata(self) -> dict[str, Any]:
        if self._metadata is None or time.monotonic() - self._metadata_at > _CACHE_TTL:
            url = self.config.issuer.rstrip("/") + "/.well-known/openid-configuration"
            response = await self._request("GET", url)
            if response.status_code != 200:
                raise OidcError("SSO provider discovery failed")
            metadata = response.json()
            if metadata.get("issuer", "").rstrip("/") != self.config.issuer.rstrip("/"):
                raise OidcError("SSO provider issuer mismatch")
            self._metadata, self._metadata_at = metadata, time.monotonic()
        return self._metadata

    async def _signing_key(self, kid: str | None) -> jwt.PyJWK:
        for attempt in range(2):
            # Refetch once on unknown kid: the IdP may have rotated its keys.
            stale = time.monotonic() - self._jwks_at > _CACHE_TTL
            if self._jwks is None or stale or attempt == 1:
                response = await self._request("GET", (await self.metadata())["jwks_uri"])
                if response.status_code != 200:
                    raise OidcError("SSO provider key fetch failed")
                self._jwks, self._jwks_at = (
                    jwt.PyJWKSet.from_dict(response.json()),
                    time.monotonic(),
                )
            keys = [k for k in self._jwks.keys if kid is None or k.key_id == kid]
            if len(keys) == 1:
                return keys[0]
            if kid is None and keys:
                raise OidcError("SSO token has no key id and provider has several keys")
        raise OidcError("SSO token signed with unknown key")

    async def authorization_url(self, state: str, nonce: str, code_challenge: str) -> str:
        endpoint = (await self.metadata())["authorization_endpoint"]
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri(self.config),
            "scope": " ".join(self.config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{endpoint}?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(self.config),
            "code_verifier": code_verifier,
            "client_id": self.config.client_id,
        }
        auth = None
        if self.config.client_secret:
            auth = httpx.BasicAuth(self.config.client_id, self.config.client_secret)
        response = await self._request(
            "POST", (await self.metadata())["token_endpoint"], data=data, auth=auth
        )
        if response.status_code != 200:
            raise OidcError("SSO code exchange failed")
        tokens = response.json()
        if "id_token" not in tokens:
            raise OidcError("SSO provider returned no ID token")
        return tokens

    async def validate_id_token(
        self, id_token: str, audiences: list[str], nonce: str | None, max_age: int | None = None
    ) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OidcError("Invalid SSO token") from exc
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            raise OidcError("SSO token uses a disallowed algorithm")
        key = await self._signing_key(header.get("kid"))
        metadata = await self.metadata()
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=[header["alg"]],
                audience=audiences,
                issuer=metadata["issuer"],
                leeway=_CLOCK_LEEWAY,
                options={"require": ["iss", "sub", "aud", "exp", "iat"]},
            )
        except jwt.PyJWTError as exc:
            raise OidcError("Invalid SSO token") from exc
        aud = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        if len(aud) > 1 and claims.get("azp") not in audiences:
            raise OidcError("Invalid SSO token")
        if nonce is not None and not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("Invalid SSO token")
        if max_age is not None and claims["iat"] < time.time() - max_age - _CLOCK_LEEWAY:
            raise OidcError("SSO token too old, sign in again")
        return claims

    async def userinfo(self, access_token: str) -> dict[str, Any]:
        endpoint = (await self.metadata()).get("userinfo_endpoint")
        if not endpoint:
            return {}
        response = await self._request(
            "GET", endpoint, headers={"Authorization": f"Bearer {access_token}"}
        )
        return response.json() if response.status_code == 200 else {}

    async def end_session_url(self, post_logout_redirect: str) -> str | None:
        endpoint = (await self.metadata()).get("end_session_endpoint")
        if not endpoint:
            return None
        query = urlencode(
            {"client_id": self.config.client_id, "post_logout_redirect_uri": post_logout_redirect}
        )
        return f"{endpoint}?{query}"


_clients: dict[str, OidcClient] = {}


def get_client(name: str) -> OidcClient:
    provider = get_provider(name)
    client = _clients.get(name)
    if client is None or client.config is not provider:
        client = _clients[name] = OidcClient(provider)
    return client


async def claims_with_userinfo(
    client: OidcClient, claims: dict[str, Any], access_token: str | None
) -> dict[str, Any]:
    """Some IdPs (Authelia by default, Keycloak without the ID token email mapper) only
    expose groups, profile or email in userinfo."""
    config = client.config
    missing = any(c not in claims for c in (config.groups_claim, config.username_claim, "email"))
    if not access_token or not missing:
        return claims
    info = await client.userinfo(access_token)
    if info.get("sub") != claims["sub"]:
        return claims
    return {**info, **claims}
