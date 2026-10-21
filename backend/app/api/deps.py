import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import session_alive, unsign
from app.models import Role, User

ACCESS_COOKIE = "tcg_access"
REFRESH_COOKIE = "tcg_refresh"
# Browsers cannot send custom headers cross-site without a CORS preflight, so requiring
# one on cookie-authenticated writes blocks CSRF.
CSRF_HEADER = "X-TCG-CSRF"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def check_csrf(request: Request) -> None:
    if request.method not in _SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing {CSRF_HEADER} header")


async def current_user(request: Request, session: SessionDep) -> User:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    else:
        token = request.cookies.get(ACCESS_COOKIE)
        if token:
            check_csrf(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        claims = unsign(token, audience="access")
        session_id = uuid.UUID(claims["sid"])
        version = int(claims["ver"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        # Tokens issued before 0.14.0 have no session: clients refresh them.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    user = await session.get(User, int(claims["sub"]))
    if user is None or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account unavailable")
    # Password changed, account disabled, or this session logged out.
    if version != user.auth_version or not await session_alive(session, session_id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session ended")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
