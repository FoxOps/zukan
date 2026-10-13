from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminUser, SessionDep
from app.api.schemas import UserCreateIn, UserOut, UserUpdateIn
from app.core.security import hash_password
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])


async def _get_user(session: SessionDep, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("")
async def list_users(_: AdminUser, session: SessionDep) -> list[UserOut]:
    users = await session.scalars(select(User).order_by(User.username))
    return [UserOut.model_validate(u) for u in users]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreateIn, _: AdminUser, session: SessionDep) -> UserOut:
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
    if "password" in fields:
        password = fields.pop("password")
        user.password_hash = hash_password(password) if password else None
    for key, value in fields.items():
        setattr(user, key, value)
    await session.commit()
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, admin: AdminUser, session: SessionDep):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete yourself")
    await session.delete(await _get_user(session, user_id))
    await session.commit()
