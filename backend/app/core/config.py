from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TCG_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://tcg:tcg@localhost:5432/tcg"
    secret_key: str = "change-me"

    # Public URL of the site. Web UI is served at `/`, API at `/api`.
    # OIDC redirect URIs are built from it.
    public_url: str = "http://localhost:5173"

    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 30 * 24 * 3600
    # Secure cookies need HTTPS; disable only for local development.
    cookie_secure: bool = True

    # Optional YAML file describing OIDC providers (see auth.example.yaml).
    auth_config_path: Path | None = None
    # Overridden by `local_login_enabled` in the auth YAML file when present.
    local_login_enabled: bool = True

    # Built web UI (`npm run build` in web/), served at `/` when present.
    web_dir: Path = Path("../web/dist")

    image_dir: Path = Path("data/images")
    # Folders admins can import card images from (e.g. the Sorcery Google Drive download).
    import_dir: Path = Path("data/import")

    # Worker: hours between catalog refreshes (large downloads, new sets are rare),
    # hours between price/image refreshes, and games to refresh (empty = all installed).
    catalog_interval_hours: int = 7 * 24
    sync_interval_hours: int = 24
    worker_games: list[str] = []
    user_agent: str = "Fudabako/0.1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
