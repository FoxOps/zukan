"""Map validated OIDC claims to local users."""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.oidc import OidcError, OidcProviderConfig, extract_groups
from app.models import Role, User, UserIdentity

_USERNAME_CHARS = re.compile(r"[^A-Za-z0-9._@-]+")


async def _unique_username(session: AsyncSession, wanted: str) -> str:
    base = _USERNAME_CHARS.sub("-", wanted).strip("-")[:140] or "user"
    candidate, suffix = base, 1
    while await session.scalar(select(User.id).where(User.username == candidate)):
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


async def resolve_sso_user(
    session: AsyncSession,
    provider: OidcProviderConfig,
    issuer: str,
    claims: dict[str, Any],
    link_to: User | None = None,
) -> User:
    """Find, create or link the local user for an SSO login.

    Accounts are matched on (issuer, sub) only, never on email: an IdP letting users
    set an arbitrary email must not grant access to someone else's account.
    """
    groups = extract_groups(claims, provider.groups_claim)
    if provider.allowed_groups and not groups & set(provider.allowed_groups):
        raise OidcError("Your account is not allowed to use this application")

    subject = str(claims["sub"])
    email = claims.get("email") if claims.get("email_verified", True) else None
    identity = await session.scalar(
        select(UserIdentity).where(UserIdentity.issuer == issuer, UserIdentity.subject == subject)
    )

    if link_to is not None:
        if identity is not None and identity.user_id != link_to.id:
            raise OidcError("This SSO account is already linked to another user")
        user = link_to
    elif identity is not None:
        user = await session.get(User, identity.user_id)
    else:
        if not provider.auto_create_users:
            raise OidcError("No account exists for this SSO login, ask an administrator")
        wanted = claims.get(provider.username_claim) or (email or "").split("@")[0] or subject
        user = User(username=await _unique_username(session, str(wanted)), email=email)
        session.add(user)
        await session.flush()

    if user is None or user.disabled:
        raise OidcError("This account is disabled")

    if identity is None:
        identity = UserIdentity(
            user_id=user.id, provider=provider.name, issuer=issuer, subject=subject
        )
        session.add(identity)
    identity.email = email

    if provider.admin_groups:
        user.role = Role.admin if groups & set(provider.admin_groups) else Role.user

    await session.flush()
    return user
