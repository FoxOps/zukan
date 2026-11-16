"""User groups: access to optional modules, and the built-in Administrators group.

Administrators and the other groups work the same way: a group linked to identity
provider groups takes its SSO members from the groups claim at each sign-in (they
cannot be added or removed by hand), local accounts are added by hand. The
Administrators group holds no member rows: its members are the users with the admin
role, which every check of the server reads."""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.oidc import get_auth_config
from app.models import Role, User, UserGroup, UserIdentity, user_group_member

ADMINS = "admins"
ADMINS_NAME = "Administrators"


async def admins_group(session: AsyncSession) -> UserGroup:
    """The Administrators group, created on first use. Its identity provider groups
    start as the providers' `ADMIN_GROUPS` (their former role mapping); they are then
    edited in Admin > Groups."""
    group = await session.scalar(select(UserGroup).where(UserGroup.builtin == ADMINS))
    if group is None:
        seeded: list[str] = []
        for provider in get_auth_config().providers:
            seeded += [g for g in provider.admin_groups if g not in seeded]
        group = UserGroup(name=ADMINS_NAME, builtin=ADMINS, idp_groups=seeded)
        # A group of the same name made before the built-in one: keep both visible.
        if await session.scalar(select(UserGroup.id).where(UserGroup.name == ADMINS_NAME)):
            group.name = f"{ADMINS_NAME} (built-in)"
        session.add(group)
        await session.flush()
    return group


async def is_sso(session: AsyncSession, user_id: int) -> bool:
    return bool(
        await session.scalar(select(UserIdentity.id).where(UserIdentity.user_id == user_id))
    )


async def user_group_ids(session: AsyncSession, user: User) -> set[int]:
    """Groups the user belongs to, Administrators included."""
    ids = set(
        await session.scalars(
            select(user_group_member.c.group_id).where(user_group_member.c.user_id == user.id)
        )
    )
    if user.role == Role.admin:
        ids.add((await admins_group(session)).id)
    return ids


async def member_ids(session: AsyncSession, group: UserGroup) -> list[int]:
    if group.builtin == ADMINS:
        query = select(User.id).where(User.role == Role.admin)
    else:
        query = select(user_group_member.c.user_id).where(user_group_member.c.group_id == group.id)
    return list(await session.scalars(query))


async def add_member(session: AsyncSession, group: UserGroup, user: User) -> None:
    if group.builtin == ADMINS:
        user.role = Role.admin
        return
    await session.execute(
        pg_insert(user_group_member)
        .values(group_id=group.id, user_id=user.id)
        .on_conflict_do_nothing()
    )


async def remove_member(session: AsyncSession, group: UserGroup, user: User) -> None:
    if group.builtin == ADMINS:
        user.role = Role.user
        return
    await session.execute(
        delete(user_group_member).where(
            user_group_member.c.group_id == group.id, user_group_member.c.user_id == user.id
        )
    )


async def sync_sso_groups(session: AsyncSession, user: User, claimed: set[str]) -> None:
    """Sign-in of an SSO user: membership of every group linked to identity provider
    groups follows the groups claim; groups without links are left as they are."""
    await admins_group(session)
    linked = (
        await session.scalars(select(UserGroup).where(func.cardinality(UserGroup.idp_groups) > 0))
    ).all()
    current = await user_group_ids(session, user)
    for group in linked:
        wanted = bool(claimed & set(group.idp_groups))
        if wanted and group.id not in current:
            await add_member(session, group, user)
        elif not wanted and group.id in current:
            await remove_member(session, group, user)
    await session.flush()


async def groups_by_user(session: AsyncSession, users: list[User]) -> dict[int, list[UserGroup]]:
    """Groups of each user, Administrators included, by name."""
    admins = await admins_group(session)
    rows = await session.execute(
        select(user_group_member.c.user_id, UserGroup)
        .join(UserGroup, UserGroup.id == user_group_member.c.group_id)
        .where(user_group_member.c.user_id.in_([u.id for u in users]))
    )
    result: dict[int, list[UserGroup]] = {
        u.id: [admins] if u.role == Role.admin else [] for u in users
    }
    for user_id, group in rows:
        result[user_id].append(group)
    for found in result.values():
        found.sort(key=lambda g: (g.builtin is None, g.name.lower()))
    return result
