from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.models import Role

Username = Annotated[
    str, StringConstraints(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9._@-]+$")
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=256)]
# Languages of the web interface.
UiLanguage = Literal["en", "fr"]


class IdentityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    email: str | None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    role: Role
    disabled: bool
    has_password: bool


class MeOut(UserOut):
    identities: list[IdentityOut]
    language: UiLanguage
    # Games shown in the catalog, None for all.
    catalog_games: list[str] | None
    # Main price source id (see GameOut.price_sources): values, sorts, price ranges.
    price_source: str
    # Price sources shown, main one first.
    price_sources: list[str]


class SettingsIn(BaseModel):
    """Fields left out are not changed. `catalog_games: null` shows every game."""

    language: UiLanguage | None = None
    catalog_games: list[str] | None = None
    # Makes this source the main one (the others stay shown).
    price_source: str | None = None
    # Sources shown, main one first (at least one).
    price_sources: list[str] | None = None


class TokenOut(BaseModel):
    """Token mode (mobile). Cookie mode (web) only gets the user back."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class LoginIn(BaseModel):
    username: str = Field(max_length=150)
    password: str = Field(max_length=256)
    mode: Literal["token", "cookie"] = "token"


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class OidcExchangeIn(BaseModel):
    id_token: str
    nonce: str
    # Lets the server read groups from userinfo when the ID token lacks them.
    access_token: str | None = None


class ProviderOut(BaseModel):
    name: str
    display_name: str
    issuer: str
    mobile_client_id: str | None
    scopes: list[str]


class ProvidersOut(BaseModel):
    local_login_enabled: bool
    providers: list[ProviderOut]


class EmailChangeIn(BaseModel):
    # None removes the address.
    email: EmailStr | None
    # Needed when the account has a password (SSO-only accounts have none).
    current_password: str | None = None


class PasswordChangeIn(BaseModel):
    current_password: str | None = None
    new_password: Password


class UserCreateIn(BaseModel):
    username: Username
    password: Password | None = None
    email: EmailStr | None = None
    role: Role = Role.user


class UserUpdateIn(BaseModel):
    email: EmailStr | None = None
    role: Role | None = None
    disabled: bool | None = None
    password: Password | None = None
