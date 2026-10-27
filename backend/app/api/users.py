from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminUser, SessionDep
from app.api.schemas import UserCreateIn, UserOut, UserUpdateIn
from app.core.oidc import get_auth_config, local_login_enabled
from app.core.security import end_all_sessions, hash_password
from app.models import User, UserIdentity

router = APIRouter(prefix="/users", tags=["users"])


async def _get_user(session: SessionDep, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def _sso_users(session: SessionDep, *user_ids: int) -> dict[int, bool]:
    """SSO users, mapped to whether their identity provider sets their role (its
    admin groups, applied at every login)."""
    query = select(UserIdentity.user_id, UserIdentity.provider)
    if user_ids:
        query = query.where(UserIdentity.user_id.in_(user_ids))
    role_providers = {p.name for p in get_auth_config().providers if p.admin_groups}
    sso_users: dict[int, bool] = {}
    for user_id, provider in await session.execute(query):
        sso_users[user_id] = sso_users.get(user_id, False) or provider in role_providers
    return sso_users


def _out(user: User, sso_users: dict[int, bool]) -> UserOut:
    return UserOut.model_validate(user).model_copy(
        update={"sso": user.id in sso_users, "role_managed_by_sso": sso_users.get(user.id, False)}
    )


@router.get("")
async def list_users(_: AdminUser, session: SessionDep) -> list[UserOut]:
    users = await session.scalars(select(User).order_by(User.username))
    sso_users = await _sso_users(session)
    return [_out(u, sso_users) for u in users]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreateIn, _: AdminUser, session: SessionDep) -> UserOut:
    # SSO-only setup: accounts come from the identity provider.
    if not local_login_enabled():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Local accounts are disabled")
    user = User(
        username=body.username,
        email=body.email,
        role=body.role,
        password_hash=hash_password(body.password) if body.password else None,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken") from exc
    return UserOut.model_validate(user)


@router.patch("/{user_id}")
async def update_user(
    user_id: int, body: UserUpdateIn, admin: AdminUser, session: SessionDep
) -> UserOut:
    user = await _get_user(session, user_id)
    if user.id == admin.id and (body.disabled or (body.role and body.role != admin.role)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot demote or disable yourself")
    fields = body.model_dump(exclude_unset=True)
    sso_users = await _sso_users(session, user.id)
    if sso_users and {"email", "password"} & fields.keys():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This user's email and password are managed by single sign-on",
        )
    if sso_users.get(user.id) and fields.get("role", user.role) != user.role:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This user's role is managed by single sign-on"
        )
    # A new password or a disabled account ends the user's sessions.
    ends_sessions = "password" in fields or (fields.get("disabled") and not user.disabled)
    if "password" in fields:
        password = fields.pop("password")
        user.password_hash = hash_password(password) if password else None
    for key, value in fields.items():
        setattr(user, key, value)
    if ends_sessions:
        await end_all_sessions(session, user)
    await session.commit()
    return _out(user, sso_users)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, admin: AdminUser, session: SessionDep):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete yourself")
    await session.delete(await _get_user(session, user_id))
    await session.commit()
