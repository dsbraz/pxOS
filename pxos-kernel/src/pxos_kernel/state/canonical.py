"""Governed canonical state (PXOS-7): proposal -> review -> versioned fact.

Pure rules (digest, evidence) live here as functions; the database enforces the
invariants that protect data (reviewer, approver role, self-approval, append-only).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import asyncpg

from pxos_kernel.errors import PxosError
from pxos_kernel.identity import Connection, NotAuthorized
from pxos_kernel.ontology import RegisteredPackage, Registry

Decision = Literal["approved", "rejected"]
Operation = Literal["assert", "invalidate"]


class InvalidProposal(PxosError):
    """The proposal is incomplete or inconsistent."""


class DigestMismatch(PxosError):
    """The reviewer did not review exactly this proposal."""


class SelfApproval(NotAuthorized):
    """The author (or whoever they act for) tried to review their own proposal."""


class NotApprover(NotAuthorized):
    """The reviewer does not hold the approver role declared by the package."""


class StalePackage(PxosError):
    """The package changed after the proposal; a new proposal is needed."""


class StaleRevision(PxosError):
    """Another proposal on the same revision was approved first."""


class DecisionFinal(PxosError):
    """The proposal already has a different final decision."""


@dataclass(frozen=True)
class Evidence:
    source: str
    quote: str
    context_ref: str

    def as_dict(self) -> dict[str, str]:
        return {"source": self.source, "quote": self.quote, "context_ref": self.context_ref}


@dataclass(frozen=True)
class Proposal:
    id: UUID
    package: str
    package_version: str
    package_digest: str
    action: str
    type_name: str
    entity_id: UUID
    base_revision: int
    operation: Operation
    valid_from: datetime
    valid_to: datetime | None
    payload: dict[str, Any]
    evidence: dict[str, str]
    digest: str
    author: str
    author_principal: str
    created_at: datetime


@dataclass(frozen=True)
class Review:
    proposal_id: UUID
    decision: Decision
    reason: str | None
    proposal_digest: str
    reviewer: str
    reviewer_principal: str
    decided_at: datetime


@dataclass(frozen=True)
class Fact:
    entity_id: UUID
    revision: int
    package: str
    type_name: str
    operation: Operation
    payload: dict[str, Any]
    evidence: dict[str, str]
    valid_from: datetime
    valid_to: datetime | None
    proposal_id: UUID
    known_at: datetime


def proposal_digest(content: dict[str, Any]) -> str:
    """Identity of exactly what a reviewer sees; any change produces another digest."""
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def check_evidence(evidence: Evidence) -> None:
    for name, value in evidence.as_dict().items():
        if not value.strip():
            raise InvalidProposal(f"evidence {name} is required")


async def propose(
    connection: Connection,
    registered: RegisteredPackage,
    action: str,
    *,
    payload: dict[str, Any],
    evidence: Evidence,
    valid_from: datetime,
    valid_to: datetime | None = None,
    entity_id: UUID | None = None,
    base_revision: int = 0,
) -> Proposal:
    """Propose asserting a full snapshot of an entity from ``valid_from``."""
    action_type = registered.package.action(action)
    if (entity_id is None) != (base_revision == 0):
        raise InvalidProposal("a new entity has base revision 0; a change names its entity")
    return await _insert(
        connection,
        registered,
        action,
        action_type.creates,
        entity_id or uuid4(),
        base_revision,
        "assert",
        valid_from,
        valid_to,
        registered.validate(action_type.creates, payload),
        evidence,
    )


async def propose_invalidation(
    connection: Connection,
    registered: RegisteredPackage,
    action: str,
    *,
    entity_id: UUID,
    base_revision: int,
    valid_from: datetime,
    evidence: Evidence,
) -> Proposal:
    """Propose that an entity stops being valid from ``valid_from``; history stays."""
    if base_revision < 1:
        raise InvalidProposal("only an existing fact can be invalidated")
    action_type = registered.package.action(action)
    return await _insert(
        connection,
        registered,
        action,
        action_type.creates,
        entity_id,
        base_revision,
        "invalidate",
        valid_from,
        None,
        {},
        evidence,
    )


async def review(
    connection: Connection,
    registry: Registry,
    proposal_id: UUID,
    decision: Decision,
    *,
    digest: str,
    reason: str | None = None,
) -> Review:
    """Record the session actor's decision on exactly the proposal they reviewed."""
    proposal = await get_proposal(connection, proposal_id)
    if registry.get(proposal.package).package.digest != proposal.package_digest:
        raise StalePackage(f"{proposal.package} changed after proposal {proposal_id}")
    try:
        async with connection.transaction():
            row = await connection.fetchrow(
                """
                INSERT INTO pxos.reviews (proposal_id, decision, reason, proposal_digest,
                                          reviewer, reviewer_principal)
                VALUES ($1, $2, $3, $4, '', '')
                RETURNING *
                """,
                proposal_id,
                decision,
                reason,
                digest,
            )
    except asyncpg.UniqueViolationError as error:
        if error.constraint_name != "reviews_pkey":
            raise _translate(error) from None
        existing = await _review(connection, proposal_id)
        if existing.decision != decision or existing.proposal_digest != digest:
            raise DecisionFinal(f"proposal {proposal_id} was already {existing.decision}") from None
        return existing
    except asyncpg.PostgresError as error:
        raise _translate(error) from None
    assert row is not None
    return Review(**dict(row))


async def get_proposal(connection: Connection, proposal_id: UUID) -> Proposal:
    row = await connection.fetchrow("SELECT * FROM pxos.proposals WHERE id = $1", proposal_id)
    if row is None:
        raise InvalidProposal(f"proposal {proposal_id} not found")
    return Proposal(**dict(row))


async def as_of(
    connection: Connection, entity_id: UUID, *, valid_at: datetime, known_at: datetime
) -> Fact | None:
    """The fact valid at ``valid_at`` as it was known at ``known_at``.

    Revisions are full snapshots from ``valid_from``. Among those known and already in
    force, the latest ``valid_from`` wins and, on the same date, the highest revision.
    An invalidation or an expired ``valid_to`` means no fact.
    """
    row = await connection.fetchrow(
        """
        SELECT * FROM pxos.facts
        WHERE entity_id = $1 AND known_at <= $3 AND valid_from <= $2
        ORDER BY valid_from DESC, revision DESC
        LIMIT 1
        """,
        entity_id,
        valid_at,
        known_at,
    )
    if row is None:
        return None
    fact = Fact(**dict(row))
    if fact.operation == "invalidate" or (fact.valid_to is not None and valid_at >= fact.valid_to):
        return None
    return fact


async def history(connection: Connection, entity_id: UUID) -> list[Fact]:
    rows = await connection.fetch(
        "SELECT * FROM pxos.facts WHERE entity_id = $1 ORDER BY revision", entity_id
    )
    return [Fact(**dict(row)) for row in rows]


async def install_packages(owner: asyncpg.Connection, registry: Registry) -> None:
    """Record the registered packages so the database knows approvers and readers."""
    async with owner.transaction():
        for registered in registry:
            package = registered.package
            await owner.execute(
                """
                INSERT INTO pxos.packages (name, version, digest) VALUES ($1, $2, $3)
                ON CONFLICT (name) DO UPDATE
                SET version = EXCLUDED.version, digest = EXCLUDED.digest
                """,
                package.name,
                package.version,
                package.digest,
            )
            await owner.executemany(
                """
                INSERT INTO pxos.package_actions (package, digest, action, creates, approver_role)
                VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING
                """,
                [
                    (package.name, package.digest, a.name, a.creates, a.approver)
                    for a in package.actions
                ],
            )
            await owner.execute("DELETE FROM pxos.type_readers WHERE package = $1", package.name)
            await owner.executemany(
                "INSERT INTO pxos.type_readers (package, type_name, role) VALUES ($1, $2, $3)",
                [
                    (package.name, type_name, role)
                    for type_name, roles in package.readers.items()
                    for role in roles
                ],
            )


async def _insert(
    connection: Connection,
    registered: RegisteredPackage,
    action: str,
    type_name: str,
    entity_id: UUID,
    base_revision: int,
    operation: Operation,
    valid_from: datetime,
    valid_to: datetime | None,
    payload: dict[str, Any],
    evidence: Evidence,
) -> Proposal:
    check_evidence(evidence)
    package = registered.package
    content = {
        "package": package.name,
        "package_version": package.version,
        "package_digest": package.digest,
        "action": action,
        "type_name": type_name,
        "entity_id": str(entity_id),
        "base_revision": base_revision,
        "operation": operation,
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat() if valid_to else None,
        "payload": payload,
        "evidence": evidence.as_dict(),
    }
    try:
        row = await connection.fetchrow(
            """
            INSERT INTO pxos.proposals (
                package, package_version, package_digest, action, type_name, entity_id,
                base_revision, operation, valid_from, valid_to, payload, evidence, digest,
                author, author_principal
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, '', '')
            RETURNING *
            """,
            package.name,
            package.version,
            package.digest,
            action,
            type_name,
            entity_id,
            base_revision,
            operation,
            valid_from,
            valid_to,
            payload,
            evidence.as_dict(),
            proposal_digest(content),
        )
    except asyncpg.PostgresError as error:
        raise _translate(error) from None
    assert row is not None
    return Proposal(**dict(row))


async def _review(connection: Connection, proposal_id: UUID) -> Review:
    row = await connection.fetchrow(
        "SELECT * FROM pxos.reviews WHERE proposal_id = $1", proposal_id
    )
    assert row is not None
    return Review(**dict(row))


def _translate(error: asyncpg.PostgresError) -> PxosError:
    """Map database refusals by SQLSTATE and constraint name, never by message text."""
    sqlstate = error.sqlstate
    if sqlstate in {"PX001", "PX002"}:
        return NotAuthorized(str(error))
    if sqlstate == "PX010":
        return DigestMismatch(str(error))
    if sqlstate == "PX011":
        return SelfApproval(str(error))
    if sqlstate == "PX012":
        return StalePackage(str(error))
    if sqlstate == "PX013":
        return NotApprover(str(error))
    if sqlstate == "PX014":
        return InvalidProposal(str(error))
    if isinstance(error, asyncpg.UniqueViolationError) and error.constraint_name == "facts_pkey":
        return StaleRevision(str(error))
    if isinstance(error, asyncpg.CheckViolationError):
        return InvalidProposal(str(error))
    raise error
