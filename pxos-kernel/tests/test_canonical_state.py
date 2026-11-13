"""Governed canonical state with the retail fixture package (PXOS-7)."""

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import pytest
import retail_fixture.generated as retail_models
import yaml

from db_testing import Database
from pxos_kernel.identity import session
from pxos_kernel.ontology import InvalidPayload, Registry
from pxos_kernel.state import (
    DecisionFinal,
    DigestMismatch,
    Evidence,
    InvalidProposal,
    NotApprover,
    Proposal,
    SelfApproval,
    StalePackage,
    StaleRevision,
    as_of,
    get_proposal,
    history,
    propose,
    propose_invalidation,
    review,
)

RETAIL = Path(__file__).parent / "retail_fixture"
EVIDENCE = Evidence(
    source="fixture:shelf-log-2026-11-01",
    quote="Repor 3 unidades do SKU A-1",
    context_ref="fixture:ctx-retail-1",
)
NOV = {day: datetime(2026, 11, day, tzinfo=UTC) for day in range(1, 31)}
LATER = datetime(2100, 1, 1, tzinfo=UTC)


def order(quantity: int) -> dict[str, Any]:
    return {"sku": "A-1", "quantity": quantity, "occurred_at": "2026-11-01T09:00:00Z"}


async def new_proposal(
    pool: asyncpg.Pool,
    registry: Registry,
    *,
    quantity: int = 3,
    valid_from: datetime = NOV[1],
    valid_to: datetime | None = None,
    entity_id: UUID | None = None,
    base_revision: int = 0,
    author: str = "erin",
) -> Proposal:
    async with session(pool, author) as connection:
        return await propose(
            connection,
            registry.get("retail"),
            "create_restock_order",
            payload=order(quantity),
            evidence=EVIDENCE,
            valid_from=valid_from,
            valid_to=valid_to,
            entity_id=entity_id,
            base_revision=base_revision,
        )


async def approve(pool: asyncpg.Pool, registry: Registry, proposal: Proposal) -> None:
    async with session(pool, "carla") as connection:
        await review(connection, registry, proposal.id, "approved", digest=proposal.digest)


async def read(pool: asyncpg.Pool, entity_id: UUID, valid_at: datetime, known_at: datetime) -> Any:
    async with session(pool, "erin") as connection:
        fact = await as_of(connection, entity_id, valid_at=valid_at, known_at=known_at)
    return None if fact is None else fact.payload["quantity"]


async def events(database: Database, entity_id: UUID) -> list[str]:
    owner = await asyncpg.connect(database.owner_dsn)
    try:
        rows = await owner.fetch(
            "SELECT event_type FROM pxos.outbox WHERE entity_id = $1 ORDER BY id", entity_id
        )
    finally:
        await owner.close()
    return [row["event_type"] for row in rows]


async def test_proposal_is_immutable_draft_until_approved(
    pool: asyncpg.Pool, registry: Registry, database: Database
) -> None:
    proposal = await new_proposal(pool, registry)

    assert proposal.base_revision == 0
    assert proposal.package_digest == registry.get("retail").package.digest
    assert proposal.evidence == EVIDENCE.as_dict()
    assert await read(pool, proposal.entity_id, NOV[5], LATER) is None

    await approve(pool, registry, proposal)

    async with session(pool, "erin") as connection:
        facts = await history(connection, proposal.entity_id)
    assert [(f.revision, f.payload["quantity"]) for f in facts] == [(1, 3)]
    assert facts[0].proposal_id == proposal.id
    assert facts[0].evidence["source"] == EVIDENCE.source  # req. 3: every fact has a source
    assert await events(database, proposal.entity_id) == ["proposal.created", "fact.recorded"]


async def test_rejection_records_reason_without_publishing(
    pool: asyncpg.Pool, registry: Registry, database: Database
) -> None:
    proposal = await new_proposal(pool, registry)
    async with session(pool, "carla") as connection:
        with pytest.raises(InvalidProposal):
            await review(connection, registry, proposal.id, "rejected", digest=proposal.digest)
    async with session(pool, "carla") as connection:
        decided = await review(
            connection,
            registry,
            proposal.id,
            "rejected",
            digest=proposal.digest,
            reason="SKU errado",
        )
    assert (decided.decision, decided.reason, decided.reviewer) == (
        "rejected",
        "SKU errado",
        "carla",
    )
    assert await read(pool, proposal.entity_id, NOV[5], LATER) is None
    assert await events(database, proposal.entity_id) == ["proposal.created", "proposal.rejected"]


async def test_final_decision_cannot_change_and_redelivery_is_idempotent(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    proposal = await new_proposal(pool, registry)
    async with session(pool, "carla") as connection:
        first = await review(connection, registry, proposal.id, "approved", digest=proposal.digest)
    async with session(pool, "carla") as connection:
        again = await review(connection, registry, proposal.id, "approved", digest=proposal.digest)
    assert again == first
    async with session(pool, "diego") as connection:
        with pytest.raises(DecisionFinal):
            await review(
                connection, registry, proposal.id, "rejected", digest=proposal.digest, reason="x"
            )


async def test_approval_requires_the_reviewed_digest(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    proposal = await new_proposal(pool, registry)
    async with session(pool, "carla") as connection:
        with pytest.raises(DigestMismatch):
            await review(connection, registry, proposal.id, "approved", digest="0" * 64)


@pytest.mark.parametrize(
    ("author", "reviewer", "on_behalf_of", "error"),
    [
        ("carla", "carla", None, SelfApproval),
        ("restock-agent", "carla", None, NotApprover),
        ("erin", "erin", None, SelfApproval),
        ("erin", "restock-agent", "erin", SelfApproval),
        ("erin", "restock-agent", "carla", None),
    ],
)
async def test_approver_is_declared_role_and_never_the_author(
    pool: asyncpg.Pool,
    registry: Registry,
    author: str,
    reviewer: str,
    on_behalf_of: str | None,
    error: type[Exception] | None,
) -> None:
    proposal = await new_proposal(pool, registry, author=author)
    if author == "restock-agent":
        # The agent proposes on behalf of Carla, so Carla cannot approve it either.
        async with session(pool, "restock-agent", "carla") as connection:
            proposal = await propose(
                connection,
                registry.get("retail"),
                "create_restock_order",
                payload=order(3),
                evidence=EVIDENCE,
                valid_from=NOV[1],
            )
        error = SelfApproval
    async with session(pool, reviewer, on_behalf_of) as connection:
        if error is None:
            decided = await review(
                connection, registry, proposal.id, "approved", digest=proposal.digest
            )
            assert (decided.reviewer, decided.reviewer_principal) == (reviewer, on_behalf_of)
        else:
            with pytest.raises(error):
                await review(connection, registry, proposal.id, "approved", digest=proposal.digest)


async def test_staff_without_approver_role_cannot_approve(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    proposal = await new_proposal(pool, registry, author="carla")
    async with session(pool, "erin") as connection:
        with pytest.raises(NotApprover):
            await review(connection, registry, proposal.id, "approved", digest=proposal.digest)


async def test_package_change_invalidates_open_proposals(
    pool: asyncpg.Pool, registry: Registry, tmp_path: Path
) -> None:
    proposal = await new_proposal(pool, registry)

    changed_dir = tmp_path / "retail"
    shutil.copytree(RETAIL, changed_dir)
    manifest = yaml.safe_load((changed_dir / "manifest.yaml").read_text(encoding="utf-8"))
    manifest["actions"][0]["reversible"] = False
    (changed_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    changed = Registry()
    changed.register(changed_dir, retail_models)

    async with session(pool, "carla") as connection:
        with pytest.raises(StalePackage):
            await review(connection, changed, proposal.id, "approved", digest=proposal.digest)


async def test_database_refuses_review_after_installed_package_changed(
    pool: asyncpg.Pool, registry: Registry, database: Database
) -> None:
    proposal = await new_proposal(pool, registry)
    owner = await asyncpg.connect(database.owner_dsn)
    transaction = owner.transaction()
    await transaction.start()
    try:
        await owner.execute("UPDATE pxos.packages SET digest = 'changed' WHERE name = 'retail'")
        await owner.execute("SELECT set_config('pxos.actor', 'carla', true)")
        with pytest.raises(asyncpg.PostgresError) as error:
            await owner.execute(
                """
                INSERT INTO pxos.reviews (proposal_id, decision, proposal_digest,
                                          reviewer, reviewer_principal)
                VALUES ($1, 'approved', $2, '', '')
                """,
                proposal.id,
                proposal.digest,
            )
        assert error.value.sqlstate == "PX012"
    finally:
        await transaction.rollback()  # keep the installed package for the other tests
        await owner.close()


async def test_invalid_payload_and_missing_evidence_are_rejected(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    retail = registry.get("retail")
    async with session(pool, "erin") as connection:
        with pytest.raises(InvalidPayload):
            await propose(
                connection,
                retail,
                "create_restock_order",
                payload=order(0),
                evidence=EVIDENCE,
                valid_from=NOV[1],
            )
        with pytest.raises(InvalidProposal, match="evidence quote"):
            await propose(
                connection,
                retail,
                "create_restock_order",
                payload=order(1),
                evidence=Evidence(source="fixture:x", quote=" ", context_ref="fixture:y"),
                valid_from=NOV[1],
            )


async def test_retroactive_correction_and_two_date_reading(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    created = await new_proposal(pool, registry, quantity=3)
    await approve(pool, registry, created)
    entity = created.entity_id

    correction = await new_proposal(
        pool, registry, quantity=5, entity_id=entity, base_revision=1, valid_from=NOV[1]
    )
    async with session(pool, "erin") as connection:
        assert (await get_proposal(connection, correction.id)).base_revision == 1
    await approve(pool, registry, correction)

    async with session(pool, "erin") as connection:
        first, second = await history(connection, entity)
    assert (first.revision, first.payload["quantity"]) == (1, 3)
    assert (second.revision, second.payload["quantity"]) == (2, 5)

    assert await read(pool, entity, NOV[5], first.known_at) == 3
    assert await read(pool, entity, NOV[5], second.known_at) == 5
    assert await read(pool, entity, datetime(2026, 10, 31, tzinfo=UTC), second.known_at) is None


async def test_future_validity_and_finite_interval(pool: asyncpg.Pool, registry: Registry) -> None:
    created = await new_proposal(pool, registry, quantity=3, valid_to=NOV[20])
    await approve(pool, registry, created)
    future = await new_proposal(
        pool,
        registry,
        quantity=8,
        entity_id=created.entity_id,
        base_revision=1,
        valid_from=NOV[15],
        valid_to=NOV[20],
    )
    await approve(pool, registry, future)

    assert await read(pool, created.entity_id, NOV[10], LATER) == 3
    assert await read(pool, created.entity_id, NOV[16], LATER) == 8
    assert await read(pool, created.entity_id, NOV[25], LATER) is None


async def test_invalidation_has_a_date_and_keeps_history(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    created = await new_proposal(pool, registry)
    await approve(pool, registry, created)
    async with session(pool, "erin") as connection:
        invalidation = await propose_invalidation(
            connection,
            registry.get("retail"),
            "create_restock_order",
            entity_id=created.entity_id,
            base_revision=1,
            valid_from=NOV[10],
            evidence=EVIDENCE,
        )
    await approve(pool, registry, invalidation)

    async with session(pool, "erin") as connection:
        first, second = await history(connection, created.entity_id)
    assert second.operation == "invalidate"
    assert await read(pool, created.entity_id, NOV[12], LATER) is None
    assert await read(pool, created.entity_id, NOV[5], LATER) == 3
    assert await read(pool, created.entity_id, NOV[12], first.known_at) == 3


async def test_concurrent_proposals_on_same_revision_have_one_winner(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    created = await new_proposal(pool, registry)
    await approve(pool, registry, created)
    left, right = [
        await new_proposal(pool, registry, quantity=q, entity_id=created.entity_id, base_revision=1)
        for q in (4, 6)
    ]

    async def approve_slowly(proposal: Proposal, reviewer: str) -> str:
        try:
            async with session(pool, reviewer) as connection:
                await review(connection, registry, proposal.id, "approved", digest=proposal.digest)
                await asyncio.sleep(0.2)  # hold the transaction so both overlap
        except StaleRevision:
            return "lost"
        return "won"

    outcomes = await asyncio.gather(approve_slowly(left, "carla"), approve_slowly(right, "diego"))
    assert sorted(outcomes) == ["lost", "won"]
    async with session(pool, "erin") as connection:
        assert [f.revision for f in await history(connection, created.entity_id)] == [1, 2]


async def test_new_entity_and_change_are_distinguished(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    async with session(pool, "erin") as connection:
        with pytest.raises(InvalidProposal, match="base revision 0"):
            await propose(
                connection,
                registry.get("retail"),
                "create_restock_order",
                payload=order(1),
                evidence=EVIDENCE,
                valid_from=NOV[1],
                base_revision=1,
            )
