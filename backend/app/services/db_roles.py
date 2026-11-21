"""Runtime database role (`zukan db-roles`).

The role owning the database (POSTGRES_USER of the PostgreSQL image, a superuser) runs
the migrations. The API and the worker sign in with a role that only reads and writes
the data: no superuser, no schema changes, no other database. Run with the owner role;
safe to run again (it also sets the password).
"""

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def role_statements(app_user: str, database: str) -> list[str]:
    """SQL making `app_user` the runtime role of `database` (run by its owner), its
    password aside (`password_statement`)."""
    if not _ROLE_NAME.match(app_user):
        raise ValueError(f"Invalid database role name {app_user!r}")
    db = '"' + database.replace('"', '""') + '"'
    rights = (
        "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT -1"
    )
    return [
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{app_user}') "
        f"THEN CREATE ROLE {app_user}; END IF; END $$",
        f"ALTER ROLE {app_user} WITH {rights}",
        f"GRANT CONNECT ON DATABASE {db} TO {app_user}",
        f"GRANT USAGE ON SCHEMA public TO {app_user}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app_user}",
        f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {app_user}",
        # Tables and sequences of later migrations (made by the role running this).
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_user}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {app_user}",
    ]


def password_statement(app_user: str, password: str) -> str:
    if not password:
        raise ValueError("Set TCG_DB_APP_PASSWORD to the runtime role's password")
    return f"ALTER ROLE {app_user} PASSWORD '" + password.replace("'", "''") + "'"


def printable_sql(app_user: str, database: str) -> list[str]:
    """`role_statements` for psql, the password taken from the psql variable
    `app_password` (`psql -v app_password=...`): never written out."""
    return [*role_statements(app_user, database), f"ALTER ROLE {app_user} PASSWORD :'app_password'"]


async def apply(database_url: str | None = None) -> str:
    """Create or update the runtime role through `database_url` (default: the configured
    one, which must be the owner's). Returns the role name."""
    settings = get_settings()
    engine = create_async_engine(database_url or settings.database_url)
    try:
        async with engine.begin() as conn:
            database = await conn.scalar(text("SELECT current_database()"))
            owner = await conn.scalar(text("SELECT current_user"))
            if owner == settings.db_app_user:
                raise ValueError(
                    "zukan db-roles runs with the database owner, not the runtime role"
                )
            for statement in role_statements(settings.db_app_user, database):
                await conn.exec_driver_sql(statement)
            await conn.exec_driver_sql(
                password_statement(settings.db_app_user, settings.db_app_password)
            )
    finally:
        await engine.dispose()
    return settings.db_app_user
