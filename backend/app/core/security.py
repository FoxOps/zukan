import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import RefreshToken, User

_hasher = PasswordHasher()
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        # Still burn time so SSO-only and unknown accounts are not distinguishable.
        _hasher.hash(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def sign(payload: dict[str, Any], ttl: timedelta, audience: str) -> str:
    now = datetime.now(UTC)
    claims = {**payload, "iat": now, "exp": now + ttl, "aud": audience}
    return jwt.encode(claims, get_settings().secret_key, algorithm=_ALGORITHM)


def unsign(token: str, audience: str) -> dict[str, Any]:
    """Decode a token signed by `sign`. Raises jwt.PyJWTError when invalid."""
    return jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM], audience=audience)


def create_access_token(user: User) -> str:
    ttl = timedelta(seconds=get_settings().access_token_ttl_seconds)
    return sign({"sub": str(user.id), "role": user.role}, ttl, audience="access")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_refresh_token(
    session: AsyncSession, user: User, family_id: uuid.UUID | None = None
) -> str:
    token = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash_token(token),
            family_id=family_id or uuid.uuid4(),
            expires_at=datetime.now(UTC)
            + timedelta(seconds=get_settings().refresh_token_ttl_seconds),
        )
    )
    await session.flush()
    return token


async def rotate_refresh_token(session: AsyncSession, token: str) -> tuple[User, str] | None:
    """Exchange a refresh token for a new one. Returns None when invalid.

    Presenting an already revoked token revokes its whole family.
    """
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_token(token)).with_for_update()
    )
    if row is None:
        return None
    now = datetime.now(UTC)
    if row.revoked_at is not None:
        await revoke_family(session, row.family_id)
        return None
    if row.expires_at <= now:
        return None
    user = await session.get(User, row.user_id)
    if user is None or user.disabled:
        return None
    row.revoked_at = now
    new_token = await issue_refresh_token(session, user, row.family_id)
    return user, new_token


async def revoke_refresh_token(session: AsyncSession, token: str) -> None:
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_token(token))
    )
    if row is not None:
        await revoke_family(session, row.family_id)


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
