import asyncpg
import pytest
from sqlalchemy import make_url

from app.core.config import get_settings
from app.services import db_roles

# Quotes, colons and percent signs are kept as they are (no SQL or parameter injection).
PASSWORD = "it's:a%secret"


@pytest.fixture
def app_role(monkeypatch):
    monkeypatch.setattr(get_settings(), "db_app_user", "zukan_app_test")
    monkeypatch.setattr(get_settings(), "db_app_password", PASSWORD)


async def _connect_as_app() -> asyncpg.Connection:
    url = make_url(get_settings().database_url)
    return await asyncpg.connect(
        host=url.host,
        port=url.port,
        database=url.database,
        user="zukan_app_test",
        password=PASSWORD,
    )


async def test_runtime_role_reads_and_writes_only(app_role, session):
    await db_roles.apply()
    await db_roles.apply()  # every start runs it again
    conn = await _connect_as_app()
    try:
        role = await conn.fetchrow(
            "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
        )
        assert tuple(role) == (False, False, False)
        await conn.execute("INSERT INTO app_setting (key, value) VALUES ('db-roles', '{}')")
        assert await conn.fetchval("SELECT count(*) FROM app_setting") == 1
        await conn.execute("DELETE FROM app_setting")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("CREATE TABLE nope (id int)")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("DROP TABLE app_setting")
    finally:
        await conn.close()


def test_statements_refuse_bad_names_and_empty_password():
    with pytest.raises(ValueError):
        db_roles.role_statements("bad; DROP", "tcg")
    with pytest.raises(ValueError):
        db_roles.password_statement("zukan_app", "")


def test_printed_sql_keeps_the_password_out():
    """`zukan db-roles --print-sql` takes the password from a psql variable."""
    sql = "\n".join(db_roles.printable_sql("zukan_app", "tcg"))
    assert "PASSWORD :'app_password'" in sql
