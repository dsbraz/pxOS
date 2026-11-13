"""The single place where a transaction gets its actor (ADR 0003 §2, PXOS-50)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from asyncpg.pool import PoolConnectionProxy

from pxos_kernel.errors import PxosError

Connection = asyncpg.Connection | PoolConnectionProxy
"""A plain or pooled connection; kernel functions accept either."""


class NotAuthorized(PxosError):
    """The database refused the actor, its delegation or its role."""


@asynccontextmanager
async def session(
    pool: asyncpg.Pool, actor: str, on_behalf_of: str | None = None
) -> AsyncIterator[Connection]:
    """Open a transaction whose actor (and principal, for delegation) the database sees."""
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT set_config('pxos.actor', $1, true), set_config('pxos.on_behalf_of', $2, true)",
            actor,
            on_behalf_of or "",
        )
        try:
            await connection.execute("SELECT pxos.current_actor()")
        except asyncpg.PostgresError as error:
            if error.sqlstate in {"PX001", "PX002"}:
                raise NotAuthorized(str(error)) from None
            raise
        yield connection
