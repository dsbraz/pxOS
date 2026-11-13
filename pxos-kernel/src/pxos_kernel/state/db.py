"""Connection pool for the application role."""

import json

import asyncpg


async def _codecs(connection: asyncpg.Connection) -> None:
    for name in ("json", "jsonb"):
        await connection.set_type_codec(
            name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


async def create_pool(dsn: str) -> asyncpg.Pool:
    """Pool whose connections exchange json/jsonb as Python values."""
    return await asyncpg.create_pool(dsn, init=_codecs)
