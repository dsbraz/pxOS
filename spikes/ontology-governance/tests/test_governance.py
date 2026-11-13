import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from spike.contracts import Package
from spike.generate import ROOT, generate
from spike.store import as_of, connect, history, propose, review

CASES = [
    (
        "projects",
        {"owner": "ana", "due": "2026-12-01"},
        {"owner": "bia", "due": "2026-12-03"},
        "project-lead",
    ),
    (
        "support",
        {"assignee": "rui", "priority": "normal"},
        {"assignee": "lia", "priority": "urgent"},
        "support-lead",
    ),
]
EVIDENCE = {
    "source": "fixture:source-1",
    "quote": "Trecho sintético",
    "context_ref": "fixture:hindsight-1",
}


def submit(db, package, entity, payload, **kwargs):
    return propose(
        db,
        package,
        entity,
        payload,
        author="agent",
        evidence=EVIDENCE,
        valid_from="2026-11-01",
        **kwargs,
    )


def approve(db, proposal, reviewer, **kwargs):
    return review(
        db,
        proposal["id"],
        proposal["digest"],
        reviewer=reviewer,
        decision="approved",
        reason="Conferido",
        **kwargs,
    )


@pytest.mark.parametrize("package,payload,correction,reviewer", CASES)
def test_governed_lifecycle(package, payload, correction, reviewer):
    async def scenario():
        db = await connect()
        entity = str(uuid4())
        try:
            initial = await submit(db, package, entity, payload)
            assert await history(db, package, entity) == []
            with pytest.raises(PermissionError):
                await approve(db, initial, "outsider")
            with pytest.raises(ValueError, match="conteúdo"):
                await review(
                    db,
                    initial["id"],
                    "wrong-digest",
                    reviewer=reviewer,
                    decision="approved",
                    reason="Conferido",
                )
            assert await history(db, package, entity) == []
            await approve(db, initial, reviewer)
            await approve(db, initial, reviewer)
            before_correction = datetime.now(timezone.utc)
            pending = await submit(db, package, entity, correction, base_revision=1)
            assert len(await history(db, package, entity)) == 1
            await review(
                db,
                pending["id"],
                pending["digest"],
                reviewer=reviewer,
                decision="rejected",
                reason="Evidência insuficiente",
            )
            with pytest.raises(ValueError, match="já revisada"):
                await approve(db, pending, reviewer)
            corrected = await submit(db, package, entity, correction, base_revision=1)
            await approve(db, corrected, reviewer)
            await db.close()
            db = await connect()  # Persistência, não estado do processo.
            rows = await history(db, package, entity)
            assert [row["revision"] for row in rows] == [1, 2]
            assert rows[0]["body"]["payload"] == payload
            assert rows[1]["body"]["payload"] == correction
            assert rows[1]["body"]["evidence"] == EVIDENCE
            assert rows[1]["reviewer"] == reviewer
            previous = await as_of(
                db, package, entity, valid_on="2026-11-02", known_at=before_correction
            )
            current = await as_of(
                db, package, entity, valid_on="2026-11-02", known_at=datetime.now(timezone.utc)
            )
            assert previous["revision"] == 1
            assert current["revision"] == 2
            assert (
                await as_of(
                    db, package, entity, valid_on="2026-10-31", known_at=datetime.now(timezone.utc)
                )
                is None
            )
        finally:
            await db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "package,payload",
    [
        ("projects", {"owner": "ana", "due": "impossible"}),
        ("projects", {"due": "2026-12-01"}),
        ("projects", {"owner": "ana", "due": "2026-12-01", "priority": "urgent"}),
        ("support", {"assignee": "rui", "priority": "unknown"}),
        ("support", {"assignee": 7, "priority": "normal"}),
    ],
)
def test_package_rejects_invalid_payload(package, payload):
    with pytest.raises(ValidationError):
        Package(package).validate(payload)


@pytest.mark.parametrize("package,payload,correction,reviewer", CASES)
def test_concurrent_corrections_have_one_winner(package, payload, correction, reviewer):
    async def scenario():
        first = await connect()
        second = await connect()
        entity = str(uuid4())
        try:
            initial = await submit(first, package, entity, payload)
            await approve(first, initial, reviewer)
            a = await submit(first, package, entity, correction, base_revision=1)
            b = await submit(second, package, entity, payload, base_revision=1)
            outcomes = await asyncio.gather(
                approve(first, a, reviewer), approve(second, b, reviewer), return_exceptions=True
            )
            assert sum(result is None for result in outcomes) == 1
            assert sum(isinstance(result, ValueError) for result in outcomes) == 1
            assert len(await history(first, package, entity)) == 2
            count = await first.fetchval(
                "SELECT count(*) FROM reviews WHERE proposal_id=ANY($1::uuid[])",
                [UUID(a["id"]), UUID(b["id"])],
            )
            assert count == 1  # Decisão e fato são atômicos também na falha.
        finally:
            await first.close()
            await second.close()

    asyncio.run(scenario())


def test_future_effective_date_and_input_snapshot():
    async def scenario():
        db = await connect()
        entity = str(uuid4())
        try:
            payload = {"owner": "ana", "due": "2026-12-01"}
            initial = await submit(db, "projects", entity, payload)
            payload["owner"] = "tampered"
            initial["body"]["payload"]["owner"] = "tampered"
            await approve(db, initial, "project-lead")
            later = await propose(
                db,
                "projects",
                entity,
                payload,
                author="agent",
                evidence=EVIDENCE,
                valid_from="2026-12-01",
                base_revision=1,
            )
            await approve(db, later, "project-lead")
            now = datetime.now(timezone.utc)
            old = await as_of(db, "projects", entity, valid_on="2026-11-15", known_at=now)
            future = await as_of(db, "projects", entity, valid_on="2026-12-01", known_at=now)
            assert old["body"]["payload"]["owner"] == "ana"
            assert future["body"]["payload"]["owner"] == "tampered"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_missing_evidence_and_self_approval():
    async def scenario():
        db = await connect()
        try:
            with pytest.raises(ValueError, match="quote"):
                await propose(
                    db,
                    "projects",
                    str(uuid4()),
                    CASES[0][1],
                    author="agent",
                    evidence=EVIDENCE | {"quote": ""},
                    valid_from="2026-11-01",
                )
            own = await propose(
                db,
                "projects",
                str(uuid4()),
                CASES[0][1],
                author="project-lead",
                evidence=EVIDENCE,
                valid_from="2026-11-01",
            )
            with pytest.raises(PermissionError):
                await approve(db, own, "project-lead")
        finally:
            await db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("package", ["projects", "support"])
def test_generation_is_reproducible(package):
    assert generate(package) == (ROOT / "spike" / f"generated_{package}.py").read_text()


def test_changed_package_requires_new_proposal(monkeypatch):
    async def scenario():
        db = await connect()
        entity = str(uuid4())
        try:
            pending = await submit(db, "projects", entity, CASES[0][1])
            changed = Package("projects")
            changed.fingerprint = "new-schema-fingerprint"
            monkeypatch.setattr("spike.store.Package", lambda name: changed)
            with pytest.raises(ValueError, match="Pacote mudou"):
                await approve(db, pending, "project-lead")
            assert await history(db, "projects", entity) == []
            assert (
                await db.fetchval(
                    "SELECT count(*) FROM reviews WHERE proposal_id=$1", UUID(pending["id"])
                )
                == 0
            )
        finally:
            await db.close()

    asyncio.run(scenario())
