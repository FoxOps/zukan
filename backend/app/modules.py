"""Optional modules: extra features on top of plain Zukan. An administrator sets each
module's access (Admin > Groups):

- off: hidden and its routes refused for everyone (`modules_disabled` setting);
- everyone: each user turns it on in their settings;
- groups: on for the members of the chosen groups (`modules_access` setting), hidden
  for the others; users have nothing to turn on.

Administrators can use every module that is not off. The users' own choices are kept
whatever the access, for when a module goes back to everyone."""

from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.models import AppSetting, Role, User
from app.services import groups as user_groups

# Module ids, in the order they are shown.
MODULES = ("binder",)
SETTING_KEY = "modules_disabled"
ACCESS_KEY = "modules_access"

Mode = Literal["off", "everyone", "groups"]


@dataclass
class Access:
    mode: Mode = "everyone"
    # Groups given the module (mode "groups").
    groups: list[int] = field(default_factory=list)


@dataclass
class UserModules:
    # Modules the user can use.
    enabled: list[str]
    # Modules the user turns on or off in their settings (access "everyone").
    toggleable: list[str]
    # Modules given by a group (access "groups").
    granted: list[str]


async def _setting(session: AsyncSession, key: str) -> dict:
    row = await session.get(AppSetting, key)
    return row.value if row is not None else {}


async def _save(session: AsyncSession, key: str, value: dict) -> None:
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


async def disabled_modules(session: AsyncSession) -> list[str]:
    """Modules turned off for the whole server."""
    off = (await _setting(session, SETTING_KEY)).get("modules", [])
    return [m for m in MODULES if m in off]


async def access(session: AsyncSession) -> dict[str, Access]:
    """Access of every module."""
    off = await disabled_modules(session)
    stored = await _setting(session, ACCESS_KEY)
    result = {}
    for module in MODULES:
        given = stored.get(module) or {}
        if module in off:
            result[module] = Access("off", list(given.get("groups", [])))
        elif given.get("mode") == "groups":
            result[module] = Access("groups", list(given.get("groups", [])))
        else:
            result[module] = Access()
    return result


async def save_access(session: AsyncSession, values: dict[str, Access]) -> None:
    """Store the access of the modules given (the caller commits). The groups of an off
    module are kept for when it comes back."""
    current = await access(session)
    current.update(values)
    await _save(session, SETTING_KEY, {"modules": [m for m in MODULES if current[m].mode == "off"]})
    await _save(
        session,
        ACCESS_KEY,
        {
            m: {"mode": "groups" if a.mode == "groups" else "everyone", "groups": a.groups}
            for m, a in current.items()
        },
    )


async def forget_group(session: AsyncSession, group_id: int) -> None:
    """A deleted group no longer gives any module."""
    current = await access(session)
    for module_access in current.values():
        if group_id in module_access.groups:
            module_access.groups.remove(group_id)
    await save_access(session, current)


async def for_user(session: AsyncSession, user: User) -> UserModules:
    rules = await access(session)
    member_of = await user_groups.user_group_ids(session, user)
    enabled, toggleable, granted = [], [], []
    for module, rule in rules.items():
        if rule.mode == "everyone":
            toggleable.append(module)
            if module in user.modules:
                enabled.append(module)
        elif rule.mode == "groups" and (user.role == Role.admin or member_of & set(rule.groups)):
            granted.append(module)
            enabled.append(module)
    return UserModules(enabled, toggleable, granted)


def require_module(module: str):
    """Dependency refusing the route to users without `module` (the interface hides
    it; this stops direct API calls)."""

    async def check(user: CurrentUser, session: SessionDep) -> User:
        if module not in (await for_user(session, user)).enabled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Module '{module}' is not enabled")
        return user

    return Annotated[User, Depends(check)]
