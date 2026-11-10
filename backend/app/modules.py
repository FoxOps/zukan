"""Optional modules: extra features each user turns on in their settings (plain Zukan
without them). An administrator can turn a module off for the whole server
(`modules_disabled` setting): it is then hidden and its routes refused, the users'
choices being kept for when it comes back."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.models import AppSetting, User

# Module ids, in the order they are shown.
MODULES = ("binder",)
SETTING_KEY = "modules_disabled"


async def disabled_modules(session: AsyncSession) -> list[str]:
    """Modules turned off for the whole server."""
    row = await session.get(AppSetting, SETTING_KEY)
    if row is None:
        return []
    return [m for m in MODULES if m in row.value.get("modules", [])]


async def save_disabled(session: AsyncSession, modules: list[str]) -> list[str]:
    """Store the modules turned off (the caller commits)."""
    value = {"modules": [m for m in MODULES if m in modules]}
    row = await session.get(AppSetting, SETTING_KEY)
    if row is None:
        session.add(AppSetting(key=SETTING_KEY, value=value))
    else:
        row.value = value
    return value["modules"]


def available(disabled: list[str]) -> list[str]:
    return [m for m in MODULES if m not in disabled]


def enabled(user: User, disabled: list[str]) -> list[str]:
    """Modules the user turned on that the server offers."""
    return [m for m in user.modules if m in available(disabled)]


def require_module(module: str):
    """Dependency refusing the route to users without `module`."""

    async def check(user: CurrentUser, session: SessionDep) -> User:
        if module not in enabled(user, await disabled_modules(session)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Module '{module}' is not enabled")
        return user

    return Annotated[User, Depends(check)]
