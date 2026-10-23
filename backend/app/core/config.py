import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TCG_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://tcg:tcg@localhost:5432/tcg"
    secret_key: str = "change-me"

    # Public URL of the site. Web UI is served at `/`, API at `/api`.
    # OIDC redirect URIs are built from it.
    public_url: str = "http://localhost:5173"

    access_token_ttl_seconds: int = 60 * 60
    # Sliding: every refresh issues a new token with the full lifetime.
    refresh_token_ttl_seconds: int = 90 * 24 * 3600
    # Secure cookies need HTTPS; disable only for local development.
    cookie_secure: bool = True

    # SSO providers (JSON list of names); each one is configured by TCG_OIDC_<NAME>_*
    # variables (see .env.example and app.core.oidc).
    oidc_providers: list[str] = []
    local_login_enabled: bool = True
    # Administrator created on start when the database has no user yet, so the first
    # login works. Change the password after signing in. Empty password: not created.
    default_admin_username: str = "admin"
    default_admin_password: str = "changeme"

    # Sign-in limits (0: none): failed password sign-ins per account name and per client
    # address within `login_window_seconds`, then refresh and SSO requests per address and
    # minute. Answered with 429 and Retry-After.
    login_max_failures: int = 10
    login_ip_max_failures: int = 50
    login_window_seconds: int = 15 * 60
    auth_requests_per_minute: int = 60
    # Largest request body accepted (CSV imports are up to 5 MB), refused before parsing.
    max_request_bytes: int = 6 * 1024 * 1024

    # Built web UI (`npm run build` in web/), served at `/` when present.
    web_dir: Path = Path("../web/dist")

    image_dir: Path = Path("data/images")
    # Folders admins can import card images from (e.g. the Sorcery Google Drive download).
    import_dir: Path = Path("data/import")

    # Worker: hours between catalog refreshes (large downloads, new sets are rare),
    # hours between price/image refreshes, and games to refresh (empty = all installed).
    catalog_interval_hours: int = 7 * 24
    sync_interval_hours: int = 24
    # Hours between refreshes of stale cards (missed by the last catalog sync, or with
    # missing data), fetched again one by one.
    refresh_interval_hours: int = 48
    worker_games: list[str] = []
    user_agent: str = f"Zukan/{__version__}"

    # Request quotas kept by the gap-filling sources with limited free tiers (their own
    # limits: apitcg 1000 a month, tcg-api.eu 10 000 a day).
    apitcg_monthly_requests: int = 900
    tcgapi_eu_daily_requests: int = 9000
    # CardNexus API requests a day (one per game and run; their limit is 60 a minute).
    cardnexus_daily_requests: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()


def api_token(kind: str, name: str, category: str | None = None) -> str | None:
    """Token of an external API, from `TCG_APITOKEN_<KIND>_[<CATEGORY>_]<NAME>`.

    `kind` is the plugin type (GAMES, PRICES...), `category` narrows it (the game's short
    code for game sources: MTG, PKM, SOR), `name` is the API. Examples:
    TCG_APITOKEN_GAMES_RFB_RIOT, TCG_APITOKEN_PRICES_CARDNEXUS. Read from the
    environment, else from `.env`. None when unset or empty."""
    parts = ["TCG_APITOKEN", kind, *([category] if category else []), name]
    key = "_".join(part.upper().replace("-", "_") for part in parts)
    value = os.environ.get(key)
    if value is None:
        env = Path(".env")
        if env.is_file():
            value = dotenv_values(env).get(key)
    return value or None
