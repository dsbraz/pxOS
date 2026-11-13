"""The database is the guardian (ADR 0003 §2; PXOS-50, PXOS-51).

These tests send raw SQL as the application login, as a buggy application would, so a
pass means the database refused, not the Python code.
"""

from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import pytest

from db_testing import Database
from pxos_kernel.identity import NotAuthorized, session
from pxos_kernel.ontology import Registry
from pxos_kernel.state import Evidence, propose, review

EVIDENCE = Evidence(source="fixture:shelf-log", quote="restock 3", context_ref="fixture:ctx-1")
PAYLOAD = {"sku": "A-1", "quantity": 3, "occurred_at": "2026-11-01T09:00:00Z"}


async def approved_fact(pool: asyncpg.Pool, registry: Registry) -> UUID:
    retail = registry.get("retail")
    async with session(pool, "erin") as connection:
        proposal = await propose(
            connection,
            retail,
            "create_restock_order",
            payload=PAYLOAD,
            evidence=EVIDENCE,
            valid_from=datetime(2026, 11, 1, tzinfo=UTC),
        )
    async with session(pool, "carla") as connection:
        await review(connection, registry, proposal.id, "approved", digest=proposal.digest)
    return proposal.entity_id


async def test_application_login_has_no_owner_powers(database: Database) -> None:
    connection = await asyncpg.connect(database.app_dsn)
    try:
        role = await connection.fetchrow(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        assert role is not None
        assert role["rolsuper"] is False and role["rolbypassrls"] is False
        assert await connection.fetchval("SELECT pg_has_role(current_user, 'pxos_app', 'member')")
        owned = await connection.fetchval(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'pxos' AND tableowner = current_user"
        )
        assert owned == 0
        forced = await connection.fetch(
            """
            SELECT relname FROM pg_class
            WHERE relnamespace = 'pxos'::regnamespace AND relforcerowsecurity
            """
        )
        assert {row["relname"] for row in forced} == {"proposals", "reviews", "facts"}
    finally:
        await connection.close()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE pxos.facts SET payload = '{}'",
        "DELETE FROM pxos.facts",
        "TRUNCATE pxos.facts",
        "UPDATE pxos.proposals SET payload = '{}'",
        "DELETE FROM pxos.proposals",
        "UPDATE pxos.reviews SET decision = 'rejected'",
        "DELETE FROM pxos.reviews",
        "INSERT INTO pxos.facts (entity_id, revision, package, type_name, operation, payload,"
        " evidence, valid_from, proposal_id) VALUES (gen_random_uuid(), 1, 'retail',"
        " 'RestockOrder', 'assert', '{}', '{}', now(), gen_random_uuid())",
        "INSERT INTO pxos.outbox (event_type, entity_id, payload)"
        " VALUES ('x', gen_random_uuid(), '{}')",
        "SELECT * FROM pxos.outbox",
        "INSERT INTO pxos.actor_roles (actor_id, role) VALUES ('frank', 'store-manager')",
        "UPDATE pxos.packages SET digest = 'x'",
    ],
)
async def test_application_cannot_change_history_or_configuration(
    pool: asyncpg.Pool, statement: str
) -> None:
    async with pool.acquire() as connection:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.execute(statement)


async def test_reading_without_an_actor_is_refused(pool: asyncpg.Pool, registry: Registry) -> None:
    await approved_fact(pool, registry)
    async with pool.acquire() as connection:
        with pytest.raises(asyncpg.PostgresError) as error:
            await connection.fetch("SELECT * FROM pxos.facts")
    assert error.value.sqlstate == "PX001"


async def test_pooled_connection_does_not_keep_the_previous_actor(
    database: Database, pool: asyncpg.Pool, registry: Registry
) -> None:
    await approved_fact(pool, registry)
    single = await asyncpg.create_pool(database.app_dsn, min_size=1, max_size=1)
    try:
        async with session(single, "erin") as connection:
            await connection.fetch("SELECT * FROM pxos.facts")
        async with single.acquire() as connection:
            with pytest.raises(asyncpg.PostgresError) as error:
                await connection.fetch("SELECT * FROM pxos.facts")
        assert error.value.sqlstate == "PX001"
    finally:
        await single.close()


@pytest.mark.parametrize(
    ("actor", "on_behalf_of"),
    [("nobody", None), ("restock-agent", "diego"), ("carla", "erin")],
)
async def test_session_actor_must_be_a_known_actor_with_delegation(
    pool: asyncpg.Pool, actor: str, on_behalf_of: str | None
) -> None:
    with pytest.raises(NotAuthorized):
        async with session(pool, actor, on_behalf_of):
            pass


async def test_restricted_read_is_denied_by_the_database(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    entity_id = await approved_fact(pool, registry)
    unfiltered = "SELECT entity_id FROM pxos.facts WHERE entity_id = $1"

    visible = {}
    for actor, on_behalf_of in [
        ("erin", None),
        ("carla", None),
        ("frank", None),
        ("restock-agent", None),
        ("restock-agent", "erin"),
    ]:
        async with session(pool, actor, on_behalf_of) as connection:
            visible[(actor, on_behalf_of)] = bool(await connection.fetch(unfiltered, entity_id))

    assert visible == {
        ("erin", None): True,
        ("carla", None): True,
        ("frank", None): False,
        ("restock-agent", None): False,
        ("restock-agent", "erin"): True,
    }


async def test_author_and_reviewer_come_from_the_session(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    retail = registry.get("retail")
    async with session(pool, "erin") as connection:
        proposal = await propose(
            connection,
            retail,
            "create_restock_order",
            payload=PAYLOAD,
            evidence=EVIDENCE,
            valid_from=datetime(2026, 11, 1, tzinfo=UTC),
        )
    assert proposal.author == "erin"

    async with session(pool, "diego") as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO pxos.reviews (proposal_id, decision, proposal_digest,
                                      reviewer, reviewer_principal)
            VALUES ($1, 'approved', $2, 'carla', 'carla') RETURNING reviewer
            """,
            proposal.id,
            proposal.digest,
        )
    assert row is not None and row["reviewer"] == "diego"


@pytest.mark.parametrize(
    ("reviewer", "on_behalf_of", "sqlstate"),
    [
        ("erin", None, "PX011"),
        ("restock-agent", "erin", "PX011"),
        ("frank", None, "PX013"),
        ("restock-agent", None, "PX013"),
    ],
)
async def test_database_refuses_self_approval_and_missing_role(
    pool: asyncpg.Pool,
    registry: Registry,
    reviewer: str,
    on_behalf_of: str | None,
    sqlstate: str,
) -> None:
    retail = registry.get("retail")
    async with session(pool, "erin") as connection:
        proposal = await propose(
            connection,
            retail,
            "create_restock_order",
            payload=PAYLOAD,
            evidence=EVIDENCE,
            valid_from=datetime(2026, 11, 1, tzinfo=UTC),
        )
    async with session(pool, reviewer, on_behalf_of) as connection:
        with pytest.raises(asyncpg.PostgresError) as error:
            await connection.execute(
                """
                INSERT INTO pxos.reviews (proposal_id, decision, proposal_digest,
                                          reviewer, reviewer_principal)
                VALUES ($1, 'approved', $2, '', '')
                """,
                proposal.id,
                proposal.digest,
            )
    assert error.value.sqlstate == sqlstate
