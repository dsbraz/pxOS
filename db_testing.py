"""Shared test database helpers for pxos-kernel and brq-at-work tests.

Integration tests need the Compose Postgres (or PXOS_TEST_DATABASE_URL). They fail, not
skip, when it is absent. The schema is migrated by the owner; tests connect as a login
that is only a member of pxos_app, so RLS and grants are what production sees.
"""

import asyncio
import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from pxos_kernel.state import upgrade

ADMIN_DSN = os.environ.get(
    "PXOS_TEST_DATABASE_URL", "postgresql://pxos:pxos-local@127.0.0.1:25432/postgres"
)
APP_LOGIN = "pxos_app_test"
APP_PASSWORD = "pxos-app-test"


@dataclass(frozen=True)
class Database:
    owner_dsn: str
    app_dsn: str


def _with(dsn: str, *, database: str, user: str | None = None, password: str | None = None) -> str:
    parts = urlsplit(dsn)
    host = parts.hostname or "127.0.0.1"
    port = f":{parts.port}" if parts.port else ""
    user = user or parts.username or ""
    password = password if password is not None else (parts.password or "")
    credentials = f"{user}:{password}@" if password else f"{user}@"
    return urlunsplit((parts.scheme, f"{credentials}{host}{port}", f"/{database}", "", ""))


def create_test_database(name: str) -> Database:
    """Recreate ``name``, migrate it and make sure the application login exists."""

    async def recreate() -> None:
        admin = await asyncpg.connect(ADMIN_DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await admin.execute(f'CREATE DATABASE "{name}"')
        finally:
            await admin.close()

    async def app_login(owner_dsn: str) -> None:
        owner = await asyncpg.connect(owner_dsn)
        try:
            await owner.execute(
                f"""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_LOGIN}') THEN
                        CREATE ROLE {APP_LOGIN} LOGIN PASSWORD '{APP_PASSWORD}'
                            NOSUPERUSER NOBYPASSRLS IN ROLE pxos_app;
                    END IF;
                END $$
                """
            )
        finally:
            await owner.close()

    asyncio.run(recreate())
    owner_dsn = _with(ADMIN_DSN, database=name)
    upgrade(owner_dsn)
    asyncio.run(app_login(owner_dsn))
    return Database(
        owner_dsn=owner_dsn,
        app_dsn=_with(ADMIN_DSN, database=name, user=APP_LOGIN, password=APP_PASSWORD),
    )
