"""Alembic environment: explicit SQL migrations run over asyncpg (ADR 0003 §2)."""

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None, version_table_schema="public")
    with context.begin_transaction():
        context.run_migrations()


async def main() -> None:
    engine = create_async_engine(context.config.get_main_option("sqlalchemy.url") or "")
    async with engine.connect() as connection:
        await connection.run_sync(run)
    await engine.dispose()


asyncio.run(main())
