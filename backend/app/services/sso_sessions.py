"""Sessions started by an SSO sign-in follow the identity provider.

Zukan keeps its own sessions (refresh token families) after an SSO sign-in. So that an
account withdrawn at the identity provider loses access to Zukan:

- every SSO session ends `TCG_SSO_SESSION_MAX_AGE_SECONDS` after its sign-in, whatever
  the activity; the user then signs in at the provider again;
- web sessions keep the provider's refresh token (encrypted) and, on a Zukan refresh at
  most every `TCG_SSO_RECHECK_SECONDS`, exchange it at the provider. A refusal (account
  deactivated, session revoked, user no longer in the allowed groups) ends the session;
  otherwise groups and role are synced again from the new claims, as at sign-in.

The app's sessions only have the lifetime: the provider's refresh token stays on the
phone.
"""

import base64
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import oidc
from app.core.config import get_settings
from app.models import SsoSession, UsedIdToken, User, UserIdentity

logger = logging.getLogger(__name__)

_warned_no_refresh: set[str] = set()


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"zukan-sso-refresh:" + get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(token: str | None) -> str | None:
    return _fernet().encrypt(token.encode()).decode() if token else None


def _decrypt(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        # TCG_SECRET_KEY changed: the session has to be started again anyway.
        return None


async def record(
    session: AsyncSession,
    family_id: uuid.UUID,
    user: User,
    provider: str,
    idp_refresh_token: str | None,
) -> None:
    """A session just started by an SSO sign-in (`idp_refresh_token`: web only)."""
    now = datetime.now(UTC)
    if idp_refresh_token is None and provider not in _warned_no_refresh:
        _warned_no_refresh.add(provider)
        logger.info(
            "SSO provider %r gave no refresh token: its sessions are not checked again "
            "until they end (TCG_SSO_SESSION_MAX_AGE_SECONDS). Request the offline_access "
            "scope to check them.",
            provider,
        )
    session.add(
        SsoSession(
            family_id=family_id,
            user_id=user.id,
            provider=provider,
            started_at=now,
            checked_at=now,
            idp_refresh_token=_encrypt(idp_refresh_token),
        )
    )
    await session.flush()


async def use_id_token(session: AsyncSession, id_token: str, max_age: int) -> bool:
    """Mark an ID token handed by the app as used: False when it already was (a token
    gives one session only)."""
    now = datetime.now(UTC)
    await session.execute(delete(UsedIdToken).where(UsedIdToken.expires_at < now))
    inserted = await session.execute(
        insert(UsedIdToken)
        .values(
            token_hash=hashlib.sha256(id_token.encode()).hexdigest(),
            # Older tokens are refused anyway (max age, plus clock leeway).
            expires_at=now + timedelta(seconds=max_age + 3600),
        )
        .on_conflict_do_nothing()
        .returning(UsedIdToken.token_hash)
    )
    return inserted.scalar() is not None


async def forget(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(delete(SsoSession).where(SsoSession.family_id == family_id))


async def forget_user(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(SsoSession).where(SsoSession.user_id == user_id))


async def still_allowed(session: AsyncSession, family_id: uuid.UUID, user: User) -> bool:
    """Whether a session may be refreshed: True for non-SSO sessions; for SSO ones, False
    past their lifetime or when the identity provider no longer accepts the account."""
    row = await session.scalar(
        select(SsoSession).where(SsoSession.family_id == family_id).with_for_update()
    )
    if row is None:
        return True
    settings = get_settings()
    now = datetime.now(UTC)
    if now - row.started_at > timedelta(seconds=settings.sso_session_max_age_seconds):
        return False
    recheck = settings.sso_recheck_seconds
    if not recheck or row.idp_refresh_token is None:
        return True
    # Concurrent refreshes wait on the row lock, then see it checked.
    if now - row.checked_at < timedelta(seconds=recheck):
        return True
    refresh_token = _decrypt(row.idp_refresh_token)
    if refresh_token is None:
        return False
    try:
        client = oidc.get_client(row.provider)
    except oidc.OidcError:
        # Provider removed from the configuration.
        return False
    try:
        tokens = await client.refresh(refresh_token)
    except oidc.OidcUnavailable as exc:
        # Provider down: keep the session, ask again on the next refresh.
        logger.warning("SSO provider %r not checked: %s", row.provider, exc)
        return True
    except oidc.OidcError:
        return False
    try:
        claims = await _claims(session, client, row, tokens)
        from app.services.sso import resolve_sso_user

        issuer = (await client.metadata())["issuer"]
        await resolve_sso_user(session, client.config, issuer, claims)
    except oidc.OidcUnavailable as exc:
        logger.warning("SSO provider %r not checked: %s", row.provider, exc)
        return True
    except oidc.OidcError:
        return False
    row.checked_at = now
    if tokens.get("refresh_token"):
        row.idp_refresh_token = _encrypt(tokens["refresh_token"])
    await session.refresh(user)
    return not user.disabled


async def _claims(
    session: AsyncSession, client: oidc.OidcClient, row: SsoSession, tokens: dict
) -> dict:
    """Claims of the refreshed sign-in, for the same subject as the session's account."""
    identities = (
        await session.scalars(
            select(UserIdentity).where(
                UserIdentity.user_id == row.user_id, UserIdentity.provider == row.provider
            )
        )
    ).all()
    subjects = {i.subject for i in identities}
    if tokens.get("id_token"):
        claims = await client.validate_id_token(
            tokens["id_token"], [client.config.client_id], nonce=None
        )
    elif tokens.get("access_token"):
        claims = await client.userinfo(tokens["access_token"])
        if not claims.get("sub"):
            raise oidc.OidcError("SSO provider gave no claims")
    else:
        raise oidc.OidcError("SSO provider gave no token")
    if str(claims.get("sub")) not in subjects:
        raise oidc.OidcError("SSO subject changed")
    return await oidc.claims_with_userinfo(client, claims, tokens.get("access_token"))
