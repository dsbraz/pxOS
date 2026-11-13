"""Exit criterion of slice 1 (PXOS-46): the canonical cycle with the work context package
and, unchanged, with the kernel's fixture package from another domain.

That no work context type appears in pxos-kernel/ is checked by the kernel's
neutrality test.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

from pxos_kernel.identity import session
from pxos_kernel.ontology import Registry
from pxos_kernel.state import (
    Evidence,
    NotApprover,
    SelfApproval,
    as_of,
    history,
    propose,
    review,
)


@dataclass(frozen=True)
class Cycle:
    package: str
    action: str
    proposer: str
    peer: str
    approver: str
    evidence: Evidence
    payload: dict[str, Any]
    corrected: dict[str, Any]
    field: str


CYCLES = [
    Cycle(
        package="work_context",
        action="create_commitment",
        proposer="bruno",
        peer="celia",
        approver="ana",
        evidence=Evidence(
            source="fixture:transcript/2026-11-10-kickoff",
            quote="Bruno: eu entrego o protótipo até o dia 28.",
            context_ref="fixture:context/kickoff-0001",
        ),
        payload={
            "description": "Entregar o protótipo",
            "owner": "bruno",
            "due_date": "2026-11-28",
            "work_stream": "onboarding-app",
        },
        corrected={
            "description": "Entregar o protótipo",
            "owner": "bruno",
            "due_date": "2026-11-21",
            "work_stream": "onboarding-app",
        },
        field="due_date",
    ),
    Cycle(
        package="retail",
        action="create_restock_order",
        proposer="erin",
        peer="gina",
        approver="carla",
        evidence=Evidence(
            source="fixture:shelf-log-2026-11-10",
            quote="Repor 3 unidades do SKU A-1",
            context_ref="fixture:ctx-retail-1",
        ),
        payload={"sku": "A-1", "quantity": 3, "occurred_at": "2026-11-10T09:00:00Z"},
        corrected={"sku": "A-1", "quantity": 5, "occurred_at": "2026-11-10T09:00:00Z"},
        field="quantity",
    ),
]

VALID_FROM = datetime(2026, 11, 10, tzinfo=UTC)
READ_AT = datetime(2026, 11, 15, tzinfo=UTC)


@pytest.mark.parametrize("cycle", CYCLES, ids=lambda cycle: cycle.package)
async def test_canonical_cycle(pool: asyncpg.Pool, registry: Registry, cycle: Cycle) -> None:
    registered = registry.get(cycle.package)

    # 1. Proposed with evidence from a synthetic source.
    async with session(pool, cycle.proposer) as connection:
        proposal = await propose(
            connection,
            registered,
            cycle.action,
            payload=cycle.payload,
            evidence=cycle.evidence,
            valid_from=VALID_FROM,
        )
    assert proposal.evidence["quote"] == cycle.evidence.quote

    # 2. Self-approval and approval without the declared role are refused.
    for reviewer, error in ((cycle.proposer, SelfApproval), (cycle.peer, NotApprover)):
        async with session(pool, reviewer) as connection:
            with pytest.raises(error):
                await review(connection, registry, proposal.id, "approved", digest=proposal.digest)

    # 3. The declared approver approves and the fact is in the canonical state.
    async with session(pool, cycle.approver) as connection:
        await review(connection, registry, proposal.id, "approved", digest=proposal.digest)
        original = await as_of(
            connection, proposal.entity_id, valid_at=READ_AT, known_at=datetime.now(UTC)
        )
    assert original is not None and original.payload == registered.validate(
        registered.package.action(cycle.action).creates, cycle.payload
    )

    # 4. A retroactive correction (same start of validity) is proposed and approved.
    async with session(pool, cycle.proposer) as connection:
        correction = await propose(
            connection,
            registered,
            cycle.action,
            payload=cycle.corrected,
            evidence=cycle.evidence,
            valid_from=VALID_FROM,
            entity_id=proposal.entity_id,
            base_revision=1,
        )
    async with session(pool, cycle.approver) as connection:
        await review(connection, registry, correction.id, "approved", digest=correction.digest)

    # 5. Reading at two knowledge instants returns each version; history stays intact.
    async with session(pool, cycle.approver) as connection:
        facts = await history(connection, proposal.entity_id)
        before = await as_of(
            connection, proposal.entity_id, valid_at=READ_AT, known_at=facts[0].known_at
        )
        after = await as_of(
            connection, proposal.entity_id, valid_at=READ_AT, known_at=facts[1].known_at
        )
    assert [fact.revision for fact in facts] == [1, 2]
    assert before is not None and after is not None
    assert str(before.payload[cycle.field]) == str(cycle.payload[cycle.field])
    assert str(after.payload[cycle.field]) == str(cycle.corrected[cycle.field])
    assert facts[0].payload == original.payload
