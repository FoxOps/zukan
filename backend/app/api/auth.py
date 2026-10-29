import secrets
from datetime import timedelta
from urllib.parse import quote, urlparse

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    CurrentUser,
    SessionDep,
    check_csrf,
)
from app.api.schemas import (
    EmailChangeIn,
    LoginIn,
    MeOut,
    OidcExchangeIn,
    PasswordChangeIn,
    ProviderOut,
    ProvidersOut,
    RefreshIn,
    SettingsIn,
    SsoAccountOut,
    TokenOut,
    UserOut,
)
from app.core import oidc, ratelimit
from app.core.config import get_settings
from app.core.security import (
    end_all_sessions,
    hash_password,
    revoke_refresh_token,
    rotate_refresh_token,
    sign,
    start_session,
    unsign,
    verify_password,
)
from app.games.base import registry
from app.models import User, UserIdentity
from app.prices.base import price_sources
from app.services.sso import resolve_sso_user

router = APIRouter(prefix="/auth", tags=["auth"])

STATE_COOKIE = "tcg_oidc_state"
SSO_PROVIDER_COOKIE = "tcg_sso_provider"
_STATE_TTL = timedelta(minutes=10)
# Max age of an ID token presented by the mobile app to the exchange endpoint.
_MOBILE_ID_TOKEN_MAX_AGE = 300
# Refresh and SSO requests: capped per client address.
_LIMITED = Depends(ratelimit.limit_auth_requests)


def _set_session_cookies(response: Response, access: str, refresh: str) -> None:
    settings = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.access_token_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api/auth",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.delete_cookie(SSO_PROVIDER_COOKIE, path="/")


def _token_out(access: str, refresh: str) -> TokenOut:
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=get_settings().access_token_ttl_seconds,
    )


def _safe_next(path: str | None) -> str:
    """Only allow local paths, to avoid open redirects."""
    path = (path or "").replace("\\", "")
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc or not path.startswith("/") or path.startswith("//"):
        return "/"
    return path


@router.get("/providers")
async def providers() -> ProvidersOut:
    return ProvidersOut(
        local_login_enabled=oidc.local_login_enabled(),
        providers=[
            ProviderOut(
                name=p.name,
                display_name=p.display_name,
                issuer=p.issuer,
                mobile_client_id=p.mobile_client_id,
                scopes=p.scopes,
                account_url=p.account_url,
            )
            for p in oidc.get_auth_config().providers
        ],
    )


@router.post("/login", response_model=TokenOut | UserOut)
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep):
    if body.mode == "cookie":
        check_csrf(request)
    if not oidc.local_login_enabled():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Local login is disabled, use SSO")
    settings = get_settings()
    window = settings.login_window_seconds
    name, address = body.username.strip().casefold(), ratelimit.client_address(request)
    wait = ratelimit.failed_by_name.retry_after(name, settings.login_max_failures, window)
    if wait is None:
        wait = ratelimit.failed_by_address.retry_after(
            address, settings.login_ip_max_failures, window
        )
    if wait is not None:
        raise ratelimit.too_many(wait)
    user = await session.scalar(select(User).where(User.username == body.username))
    valid = verify_password(body.password, user.password_hash if user else None)
    if user is None or not valid or user.disabled:
        ratelimit.failed_by_name.hit(name, window)
        ratelimit.failed_by_address.hit(address, window)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    ratelimit.failed_by_name.clear(name)
    access, refresh = await start_session(session, user)
    await session.commit()
    if body.mode == "cookie":
        _set_session_cookies(response, access, refresh)
        return UserOut.model_validate(user)
    return _token_out(access, refresh)


@router.post("/refresh", response_model=TokenOut | UserOut, dependencies=[_LIMITED])
async def refresh(body: RefreshIn, request: Request, response: Response, session: SessionDep):
    cookie_mode = body.refresh_token is None
    token = request.cookies.get(REFRESH_COOKIE) if cookie_mode else body.refresh_token
    if cookie_mode:
        check_csrf(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")
    result = await rotate_refresh_token(session, token)
    # Commit even on failure: reuse detection may have revoked a token family.
    await session.commit()
    if result is None:
        if cookie_mode:
            _clear_session_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    user, access, new_refresh = result
    if cookie_mode:
        _set_session_cookies(response, access, new_refresh)
        return UserOut.model_validate(user)
    return _token_out(access, new_refresh)


@router.post("/logout")
async def logout(body: RefreshIn, request: Request, response: Response, session: SessionDep):
    cookie_mode = body.refresh_token is None
    if cookie_mode:
        check_csrf(request)
    token = request.cookies.get(REFRESH_COOKIE) if cookie_mode else body.refresh_token
    if token:
        await revoke_refresh_token(session, token)
        await session.commit()
    end_session_url = None
    provider_name = request.cookies.get(SSO_PROVIDER_COOKIE)
    if cookie_mode and provider_name:
        try:
            client = oidc.get_client(provider_name)
            end_session_url = await client.end_session_url(get_settings().public_url)
        except oidc.OidcError:
            pass
    _clear_session_cookies(response)
    return {"end_session_url": end_session_url}


def sso_account(identities: list[UserIdentity]) -> SsoAccountOut | None:
    """Provider of the most recently linked identity still configured."""
    for identity in sorted(identities, key=lambda i: i.id, reverse=True):
        try:
            provider = oidc.get_provider(identity.provider)
        except oidc.OidcError:
            continue
        return SsoAccountOut(
            provider=provider.name,
            display_name=provider.display_name,
            account_url=provider.account_url,
        )
    return None


async def _load_me(session: SessionDep, user_id: int) -> MeOut:
    user = await session.scalar(
        select(User).where(User.id == user_id).options(selectinload(User.identities))
    )
    out = MeOut.model_validate(user)
    out.sso = bool(user.identities)
    out.sso_account = sso_account(user.identities)
    return out


async def _has_sso(session: SessionDep, user: User) -> bool:
    return bool(
        await session.scalar(select(UserIdentity.id).where(UserIdentity.user_id == user.id))
    )


@router.get("/me")
async def me(user: CurrentUser, session: SessionDep) -> MeOut:
    return await _load_me(session, user.id)


@router.patch("/me")
async def update_settings(body: SettingsIn, user: CurrentUser, session: SessionDep) -> MeOut:
    fields = body.model_dump(exclude_unset=True)
    if fields.get("language") is not None:
        user.language = fields["language"]
    if "catalog_games" in fields:
        games = fields["catalog_games"]
        if games is not None:
            unknown = set(games) - set(registry())
            if unknown:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown games: {sorted(unknown)}"
                )
            games = [g for g in registry() if g in games]
        user.catalog_games = games
    chosen = fields.get("price_sources")
    if chosen is not None:
        chosen = list(dict.fromkeys(chosen))
        if not chosen:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one price source"
            )
    if fields.get("price_source") is not None:
        main = fields["price_source"]
        chosen = [main, *(s for s in chosen or user.price_sources if s != main)]
    if chosen is not None:
        unknown = [s for s in chosen if s not in price_sources()]
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown price sources: {unknown}"
            )
        user.price_sources = chosen
    await session.commit()
    return await _load_me(session, user.id)


@router.post("/email")
async def change_email(body: EmailChangeIn, user: CurrentUser, session: SessionDep) -> MeOut:
    """Change the account's email address. Refused for SSO users: their identity provider
    manages it (copied on every SSO login)."""
    if await _has_sso(session, user):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Your email is managed by your single sign-on provider"
        )
    if user.password_hash and not verify_password(body.current_password or "", user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.email = body.email
    await session.commit()
    return await _load_me(session, user.id)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    response: Response,
    user: CurrentUser,
    session: SessionDep,
):
    """Change the password and end every session. A browser gets a new session at once;
    token clients (the app) sign in again. Refused for SSO users: their identity
    provider manages it (SSO and local accounts are separate)."""
    if await _has_sso(session, user):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Your password is managed by your single sign-on provider"
        )
    if user.password_hash and not verify_password(body.current_password or "", user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    await end_all_sessions(session, user)
    cookie_mode = not request.headers.get("Authorization", "").lower().startswith("bearer ")
    if cookie_mode:
        access, refresh = await start_session(session, user)
    await session.commit()
    if cookie_mode:
        _set_session_cookies(response, access, refresh)


# --- OpenID Connect -------------------------------------------------------------------


def _client_or_404(provider: str) -> oidc.OidcClient:
    try:
        return oidc.get_client(provider)
    except oidc.OidcError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def _login_error_redirect(message: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?error={quote(message)}", status.HTTP_303_SEE_OTHER)
    response.delete_cookie(STATE_COOKIE, path="/api/auth/oidc")
    return response


@router.get("/oidc/{provider}/login", dependencies=[_LIMITED])
async def oidc_login(provider: str, next: str = "/"):
    """Start browser SSO. SSO and local accounts are separate: an SSO login never joins
    a local account."""
    client = _client_or_404(provider)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = oidc.new_pkce_pair()
    try:
        url = await client.authorization_url(state, nonce, challenge)
    except oidc.OidcError as exc:
        return _login_error_redirect(str(exc))
    cookie = sign(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "provider": provider,
            "next": _safe_next(next),
        },
        _STATE_TTL,
        audience="oidc-state",
    )
    response = RedirectResponse(url, status.HTTP_302_FOUND)
    response.set_cookie(
        STATE_COOKIE,
        cookie,
        max_age=int(_STATE_TTL.total_seconds()),
        httponly=True,
        secure=get_settings().cookie_secure,
        # Lax is required: the IdP redirect back is a cross-site top-level navigation.
        samesite="lax",
        path="/api/auth/oidc",
    )
    return response


@router.get("/oidc/{provider}/callback", dependencies=[_LIMITED])
async def oidc_callback(
    provider: str,
    request: Request,
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    client = _client_or_404(provider)
    if error:
        return _login_error_redirect(error_description or error)
    try:
        saved = unsign(request.cookies.get(STATE_COOKIE, ""), audience="oidc-state")
    except jwt.PyJWTError:
        return _login_error_redirect("SSO session expired, try again")
    if (
        not code
        or not state
        or saved["provider"] != provider
        or not secrets.compare_digest(saved["state"], state)
    ):
        return _login_error_redirect("Invalid SSO response")

    try:
        tokens = await client.exchange_code(code, saved["verifier"])
        claims = await client.validate_id_token(
            tokens["id_token"], [client.config.client_id], nonce=saved["nonce"]
        )
        claims = await oidc.claims_with_userinfo(client, claims, tokens.get("access_token"))
        issuer = (await client.metadata())["issuer"]
        user = await resolve_sso_user(session, client.config, issuer, claims)
    except oidc.OidcError as exc:
        await session.rollback()
        return _login_error_redirect(str(exc))

    access, refresh_token = await start_session(session, user)
    await session.commit()
    response = RedirectResponse(_safe_next(saved.get("next")), status.HTTP_303_SEE_OTHER)
    response.delete_cookie(STATE_COOKIE, path="/api/auth/oidc")
    _set_session_cookies(response, access, refresh_token)
    response.set_cookie(
        SSO_PROVIDER_COOKIE,
        # The configured name (validated in settings), not the URL's.
        client.config.name,
        max_age=get_settings().refresh_token_ttl_seconds,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/oidc/{provider}/exchange", dependencies=[_LIMITED])
async def oidc_exchange(provider: str, body: OidcExchangeIn, session: SessionDep) -> TokenOut:
    """Mobile SSO: the app ran authorization code + PKCE itself (AppAuth) and hands over
    the ID token. Only the provider's mobile client is accepted as audience."""
    client = _client_or_404(provider)
    if not client.config.mobile_client_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mobile SSO not configured")
    try:
        claims = await client.validate_id_token(
            body.id_token,
            [client.config.mobile_client_id],
            nonce=body.nonce,
            max_age=_MOBILE_ID_TOKEN_MAX_AGE,
        )
        claims = await oidc.claims_with_userinfo(client, claims, body.access_token)
        issuer = (await client.metadata())["issuer"]
        user = await resolve_sso_user(session, client.config, issuer, claims)
    except oidc.OidcError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    access, refresh_token = await start_session(session, user)
    await session.commit()
    return _token_out(access, refresh_token)
