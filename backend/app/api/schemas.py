from datetime import datetime
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.models import Role

Username = Annotated[
    str, StringConstraints(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9._@-]+$")
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=256)]
# Languages of the web interface.
UiLanguage = Literal["en", "fr", "de", "es"]
UI_LANGUAGES: tuple[str, ...] = get_args(UiLanguage)


class IdentityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    email: str | None


class GroupRefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    # "admins" for the Administrators group.
    builtin: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    role: Role
    disabled: bool
    has_password: bool
    # Signs in with SSO: its identity provider manages the email (and the password).
    sso: bool = False
    # The identity provider sets the role at every login (Administrators group linked
    # to identity provider groups).
    role_managed_by_sso: bool = False
    # Groups the user belongs to (Administrators included).
    groups: list[GroupRefOut] = []


class SsoAccountOut(BaseModel):
    """Identity provider managing an SSO user's password and email."""

    provider: str
    display_name: str
    # Account page at the IdP, None when unknown.
    account_url: str | None


class MeOut(UserOut):
    identities: list[IdentityOut]
    sso_account: SsoAccountOut | None = None
    language: UiLanguage
    # False: the user never picked a language; `language` is the client's OS or browser
    # language (Accept-Language) when the interface has it, else English.
    language_chosen: bool = False
    # Games shown in the catalog, None for all.
    catalog_games: list[str] | None
    # Main price source id (see GameOut.price_sources): values, sorts, price ranges.
    price_source: str
    # Price sources shown, main one first.
    price_sources: list[str]
    # Optional modules the user can use, e.g. "binder".
    modules: list[str] = []
    # Modules the user turns on or off in their settings.
    available_modules: list[str] = []
    # Modules given by one of the user's groups (nothing to turn on).
    managed_modules: list[str] = []


class SettingsIn(BaseModel):
    """Fields left out are not changed. `catalog_games: null` shows every game."""

    language: UiLanguage | None = None
    # False: forget the user's choice, the language follows the client's OS or browser
    # again (Accept-Language). Ignored with `language` (a choice).
    language_chosen: bool | None = None
    catalog_games: list[str] | None = None
    # Makes this source the main one (the others stay shown).
    price_source: str | None = None
    # Sources shown, main one first (at least one).
    price_sources: list[str] | None = None
    # Optional modules turned on (see MeOut.available_modules).
    modules: list[str] | None = None


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
    # Account page at the IdP (password, email), None when unknown.
    account_url: str | None = None


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


class MaintenanceOut(BaseModel):
    """Users wait, administrators pass. `reason` "sync": a data sync slows the server down
    (`game_id`: game of the job running); "admin": started by the administrator `by`."""

    since: datetime
    game_id: str | None = None
    reason: Literal["sync", "admin"] = "sync"
    by: str | None = None


class MaintenanceStateOut(BaseModel):
    maintenance: MaintenanceOut | None = None


class MaintenanceIn(BaseModel):
    # On: users get the maintenance page until an administrator turns it off.
    enabled: bool


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    maintenance: MaintenanceOut | None = None
