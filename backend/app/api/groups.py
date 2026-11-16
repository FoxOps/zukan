"""User groups (Admin > Groups): who can use the optional modules, and the built-in
Administrators group (`app.services.groups`)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import AfterValidator, BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import modules
from app.api.deps import AdminUser, SessionDep
from app.models import User, UserGroup, UserIdentity
from app.services import groups

router = APIRouter(prefix="/admin/groups", tags=["admin"])

GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


def _clean(names: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    if len(cleaned) > 50 or any(len(n) > 255 for n in cleaned):
        raise ValueError("At most 50 identity provider groups of 255 characters")
    return cleaned


IdpGroups = Annotated[list[str], AfterValidator(_clean)]


class GroupMemberOut(BaseModel):
    id: int
    username: str
    disabled: bool
    sso: bool
    # Comes from the identity provider's groups claim: not changed by hand.
    managed_by_sso: bool


class GroupOut(BaseModel):
    id: int
    name: str
    # "admins" for the Administrators group (its members are the administrators).
    builtin: str | None
    # Identity provider groups whose SSO users are members, applied at each sign-in.
    idp_groups: list[str]
    members: list[GroupMemberOut]


class GroupIn(BaseModel):
    name: GroupName
    idp_groups: IdpGroups = []


class GroupUpdateIn(BaseModel):
    name: GroupName | None = None
    idp_groups: IdpGroups | None = None


async def _get(session: SessionDep, group_id: int) -> UserGroup:
    await groups.admins_group(session)
    group = await session.get(UserGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


async def _out(session: SessionDep, group: UserGroup) -> GroupOut:
    ids = await groups.member_ids(session, group)
    users = (
        await session.scalars(select(User).where(User.id.in_(ids)).order_by(User.username))
    ).all()
    sso = set(
        await session.scalars(select(UserIdentity.user_id).where(UserIdentity.user_id.in_(ids)))
    )
    return GroupOut(
        id=group.id,
        name=group.name,
        builtin=group.builtin,
        idp_groups=group.idp_groups,
        members=[
            GroupMemberOut(
                id=u.id,
                username=u.username,
                disabled=u.disabled,
                sso=u.id in sso,
                managed_by_sso=u.id in sso and bool(group.idp_groups),
            )
            for u in users
        ],
    )


async def _commit(session: SessionDep) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "A group already has this name") from exc


@router.get("")
async def list_groups(_: AdminUser, session: SessionDep) -> list[GroupOut]:
    """Every group, Administrators first."""
    await groups.admins_group(session)
    await session.commit()
    found = await session.scalars(select(UserGroup))
    ordered = sorted(found, key=lambda g: (g.builtin is None, g.name.lower()))
    return [await _out(session, g) for g in ordered]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupIn, _: AdminUser, session: SessionDep) -> GroupOut:
    await groups.admins_group(session)
    group = UserGroup(name=body.name, idp_groups=body.idp_groups)
    session.add(group)
    await _commit(session)
    return await _out(session, group)


@router.patch("/{group_id}")
async def update_group(
    group_id: int, body: GroupUpdateIn, _: AdminUser, session: SessionDep
) -> GroupOut:
    """Rename a group or change its identity provider groups (SSO members follow at
    their next sign-in)."""
    group = await _get(session, group_id)
    if body.name is not None and body.name != group.name:
        if group.builtin:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Built-in groups cannot be renamed")
        group.name = body.name
    if body.idp_groups is not None:
        group.idp_groups = body.idp_groups
    await _commit(session)
    return await _out(session, group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, _: AdminUser, session: SessionDep):
    group = await _get(session, group_id)
    if group.builtin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Built-in groups cannot be deleted")
    await modules.forget_group(session, group.id)
    await session.delete(group)
    await session.commit()


async def _member_change(
    session: SessionDep, group_id: int, user_id: int, admin: User | None = None
) -> tuple[UserGroup, User]:
    """Group and user of a membership change; `admin` when removing (never oneself
    from Administrators, so one administrator always stays)."""
    group = await _get(session, group_id)
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if group.idp_groups and await groups.is_sso(session, user.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This group's single sign-on members come from the identity provider",
        )
    if admin is not None and group.builtin == groups.ADMINS and user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot demote or disable yourself")
    return group, user


@router.put("/{group_id}/members/{user_id}")
async def add_member(group_id: int, user_id: int, _: AdminUser, session: SessionDep) -> GroupOut:
    group, user = await _member_change(session, group_id, user_id)
    await groups.add_member(session, group, user)
    await session.commit()
    return await _out(session, group)


@router.delete("/{group_id}/members/{user_id}")
async def remove_member(
    group_id: int, user_id: int, admin: AdminUser, session: SessionDep
) -> GroupOut:
    group, user = await _member_change(session, group_id, user_id, admin)
    await groups.remove_member(session, group, user)
    await session.commit()
    return await _out(session, group)
