"""Outbox publisher (PXOS-52): canonical events reach consumers at least once.

The publisher has its own role: it reads and marks the outbox and nothing else. Event
payloads carry identifiers only; consumers read content in their own session.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import asyncpg
import pytest

from db_testing import Database
from pxos_kernel.identity import session
from pxos_kernel.ontology import Registry
from pxos_kernel.state import Event, Evidence, create_pool, propose, publish, review

EVIDENCE = Evidence(source="fixture:shelf-log", quote="restock 3", context_ref="fixture:ctx-1")
PAYLOAD = {"sku": "A-1", "quantity": 3, "occurred_at": "2026-11-01T09:00:00Z"}


@pytest.fixture
async def publisher(database: Database) -> AsyncIterator[asyncpg.Pool]:
    pool = await create_pool(database.publisher_dsn)
    # Earlier tests leave events behind; start from a drained outbox.
    await publish(pool, {})
    yield pool
    await pool.close()


async def proposed(pool: asyncpg.Pool, registry: Registry, quantity: int = 3) -> str:
    async with session(pool, "erin") as connection:
        proposal = await propose(
            connection,
            registry.get("retail"),
            "create_restock_order",
            payload={**PAYLOAD, "quantity": quantity},
            evidence=EVIDENCE,
            valid_from=datetime(2026, 11, 1, tzinfo=UTC),
        )
    return str(proposal.id)


async def test_events_are_delivered_once_handled(
    pool: asyncpg.Pool, publisher: asyncpg.Pool, registry: Registry
) -> None:
    proposal_id = await proposed(pool, registry)
    seen: list[Event] = []

    async def handler(event: Event) -> None:
        seen.append(event)

    assert await publish(publisher, {"proposal.created": handler}) == 1
    assert [e.payload["proposal_id"] for e in seen] == [proposal_id]
    assert await publish(publisher, {"proposal.created": handler}) == 0
    assert len(seen) == 1


async def test_a_failing_handler_gets_the_event_again(
    pool: asyncpg.Pool, publisher: asyncpg.Pool, registry: Registry
) -> None:
    proposal_id = await proposed(pool, registry)
    attempts: list[str] = []

    async def flaky(event: Event) -> None:
        attempts.append(event.payload["proposal_id"])
        if len(attempts) == 1:
            raise RuntimeError("consumer down")

    with pytest.raises(RuntimeError):
        await publish(publisher, {"proposal.created": flaky})
    assert await publish(publisher, {"proposal.created": flaky}) == 1
    assert attempts == [proposal_id, proposal_id]


async def test_rejection_event_carries_identifiers_only(
    pool: asyncpg.Pool, publisher: asyncpg.Pool, registry: Registry
) -> None:
    await proposed(pool, registry, quantity=7)
    async with session(pool, "erin") as connection:
        row = await connection.fetchrow(
            "SELECT id, digest FROM pxos.proposals WHERE payload->>'quantity' = '7'"
        )
    assert row is not None
    async with session(pool, "carla") as connection:
        await review(
            connection, registry, row["id"], "rejected", digest=row["digest"], reason="sigiloso"
        )
    rejected: list[Event] = []

    async def handler(event: Event) -> None:
        rejected.append(event)

    await publish(publisher, {"proposal.rejected": handler})
    assert [e.payload for e in rejected] == [{"proposal_id": str(row["id"])}]


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM pxos.proposals",
        "SELECT * FROM pxos.facts",
        "INSERT INTO pxos.outbox (event_type, entity_id, payload)"
        " VALUES ('x', gen_random_uuid(), '{}')",
        "UPDATE pxos.outbox SET payload = '{}'",
        "DELETE FROM pxos.outbox",
    ],
)
async def test_publisher_reads_and_marks_the_outbox_only(
    publisher: asyncpg.Pool, statement: str
) -> None:
    async with publisher.acquire() as connection:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.execute(statement)
