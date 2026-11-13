import asyncio
import json
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from pydantic import ValidationError

from spike.gateway import connect, execute, propose, review

CASES = [
    ("project-private", {"owner": "bia", "due": "2026-12-04"}),
    ("ticket-private", {"assignee": "lia", "priority": "urgent"}),
]


@pytest.mark.parametrize("installation", ["alpha", "beta"])
@pytest.mark.parametrize("target,params", CASES)
def test_exact_approval_execution_and_audit(installation, target, params):
    async def scenario():
        agent = await connect(installation, "agent_alice")
        lead = await connect(installation, "lead")
        try:
            p = await propose(agent, target, params)
            before = await agent.fetchval("SELECT payload FROM core.resources WHERE id=$1", target)
            with pytest.raises(asyncpg.RaiseError, match="not approved"):
                await execute(agent, p)
            assert (
                await agent.fetchval("SELECT payload FROM core.resources WHERE id=$1", target)
                == before
            )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await review(agent, p)
            with pytest.raises(asyncpg.RaiseError, match="digest"):
                await review(lead, p | {"digest": "forged"})
            await review(lead, p)
            with pytest.raises(asyncpg.RaiseError, match="content mismatch"):
                await execute(agent, p | {"params": {"forged": True}})
            with pytest.raises(asyncpg.RaiseError, match="content mismatch"):
                await execute(agent, p | {"digest": "forged"})
            assert await execute(agent, p) == params
            assert await execute(agent, p) == params
            stored = await agent.fetchval("SELECT payload FROM core.resources WHERE id=$1", target)
            assert json.loads(stored) == params
            events = await agent.fetch(
                "SELECT actor,event,details FROM core.audit WHERE proposal_id=$1 ORDER BY seq",
                p["id"],
            )
            assert [(e["actor"], e["event"]) for e in events] == [
                ("agent_alice", "proposed"),
                ("lead", "approved"),
                ("agent_alice", "executed"),
            ]
            details = json.loads(events[-1]["details"])
            assert details == {
                "target": target,
                "parameters": params,
                "reviewer": "lead",
                "credential_role": "spike_owner",
                "result": "applied",
            }
            assert (
                await agent.fetchval(
                    "SELECT count(*) FROM core.effects WHERE proposal_id=$1", p["id"]
                )
                == 1
            )
        finally:
            await agent.close()
            await lead.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("installation", ["alpha", "beta"])
def test_rejection_cannot_execute(installation):
    async def scenario():
        agent = await connect(installation, "agent_alice")
        lead = await connect(installation, "lead")
        try:
            p = await propose(agent, *CASES[0])
            await review(lead, p, "rejected")
            with pytest.raises(asyncpg.RaiseError, match="not approved"):
                await execute(agent, p)
            with pytest.raises(asyncpg.RaiseError, match="already reviewed"):
                await review(lead, p)
            assert (
                await agent.fetchval(
                    "SELECT count(*) FROM core.effects WHERE proposal_id=$1", p["id"]
                )
                == 0
            )
        finally:
            await agent.close()
            await lead.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("installation", ["alpha", "beta"])
@pytest.mark.parametrize("actor", ["bob", "agent_bob"])
def test_rls_even_without_application_filter(installation, actor):
    async def scenario():
        db = await connect(installation, actor)
        try:
            assert [r["id"] for r in await db.fetch("SELECT id FROM core.resources")] == [
                "project-public"
            ]
            assert (
                await db.fetchval("SELECT payload FROM core.resources WHERE id='project-private'")
                is None
            )
            with pytest.raises(PermissionError):
                await propose(db, *CASES[0])
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await db.fetchval(
                    "SELECT core.propose($1,$2,$3::jsonb)",
                    uuid4(),
                    CASES[0][0],
                    json.dumps(CASES[0][1]),
                )
            assert (
                await db.fetchval(
                    "SELECT count(*) FROM core.proposals WHERE target='project-private'"
                )
                == 0
            )
            assert await db.fetchval("SELECT count(*) FROM core.audit") == 0
            assert await db.fetchval("SELECT count(*) FROM core.effects") == 0
            # Identidade vem da sessão autenticada, nunca de um GUC fornecido pelo chamador.
            await db.execute("SET app.user_id='alice'")
            assert await db.fetchval("SELECT core.person()") == "bob"
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await db.execute("SET ROLE spike_owner")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await db.execute("SET SESSION AUTHORIZATION alice")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await db.execute("UPDATE core.resources SET payload='{}'")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await db.execute("SELECT * FROM core.identities")
            await db.execute("SET row_security=off")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await db.fetch("SELECT * FROM core.resources")
        finally:
            await db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("installation,other", [("alpha", "beta"), ("beta", "alpha")])
def test_cross_installation_credentials_and_proposal_ids(installation, other):
    async def scenario():
        with pytest.raises(asyncpg.InvalidPasswordError):
            await connect(other, "agent_alice", credential_installation=installation)
        source = await connect(installation, "agent_alice")
        destination = await connect(other, "agent_alice")
        try:
            p = await propose(source, *CASES[0])
            assert (
                await destination.fetchval("SELECT id FROM core.proposals WHERE id=$1", p["id"])
                is None
            )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await execute(destination, p)
        finally:
            await source.close()
            await destination.close()

    asyncio.run(scenario())


def test_same_person_cannot_impersonate_requesting_agent():
    async def scenario():
        agent = await connect("alpha", "agent_alice")
        human = await connect("alpha", "alice")
        lead = await connect("alpha", "lead")
        try:
            p = await propose(agent, *CASES[0])
            await review(lead, p)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await execute(human, p)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await agent.execute("UPDATE core.proposals SET decision='approved'")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await agent.execute("DELETE FROM core.audit")
            own = await propose(lead, *CASES[0])
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await review(lead, own)
        finally:
            await agent.close()
            await human.close()
            await lead.close()

    asyncio.run(scenario())


def test_concurrent_retry_applies_effect_once():
    async def scenario():
        a = await connect("alpha", "agent_alice")
        b = await connect("alpha", "agent_alice")
        lead = await connect("alpha", "lead")
        try:
            p = await propose(a, *CASES[1])
            await review(lead, p)
            assert await asyncio.gather(execute(a, p), execute(b, p)) == [p["params"], p["params"]]
            assert (
                await a.fetchval("SELECT count(*) FROM core.effects WHERE proposal_id=$1", p["id"])
                == 1
            )
            assert (
                await a.fetchval(
                    "SELECT count(*) FROM core.audit WHERE proposal_id=$1 AND event='executed'",
                    p["id"],
                )
                == 1
            )
        finally:
            await a.close()
            await b.close()
            await lead.close()

    asyncio.run(scenario())


def test_gateway_validates_package():
    async def scenario():
        db = await connect("alpha", "agent_alice")
        try:
            with pytest.raises(ValidationError):
                await propose(db, "ticket-private", {"assignee": "lia", "priority": "invalid"})
        finally:
            await db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("package", ["projects", "support"])
def test_contracts_match_ontology_spike(package):
    root = Path(__file__).resolve().parents[1]
    previous = root.parent / "ontology-governance"
    for path in [f"packages/{package}/ontology.yaml", f"spike/generated_{package}.py"]:
        assert (root / path).read_bytes() == (previous / path).read_bytes()


def test_revoked_access_blocks_previously_approved_action():
    async def scenario():
        agent = await connect("beta", "agent_alice")
        lead = await connect("beta", "lead")
        admin = await asyncpg.connect(
            host="127.0.0.1",
            port=26433,
            database="execution_spike",
            user="postgres",
            password="local-beta-admin",
        )
        original = await admin.fetchval(
            "SELECT readers FROM core.resources WHERE id='ticket-private'"
        )
        try:
            p = await propose(agent, *CASES[1])
            await review(lead, p)
            await admin.execute(
                "UPDATE core.resources SET readers=ARRAY['lead'] WHERE id='ticket-private'"
            )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await execute(agent, p)
            assert (
                await agent.fetchval("SELECT id FROM core.resources WHERE id='ticket-private'")
                is None
            )
            assert (
                await admin.fetchval(
                    "SELECT count(*) FROM core.effects WHERE proposal_id=$1", p["id"]
                )
                == 0
            )
        finally:
            await admin.execute(
                "UPDATE core.resources SET readers=$1 WHERE id='ticket-private'", original
            )
            await admin.close()
            await agent.close()
            await lead.close()

    asyncio.run(scenario())


def test_effect_does_not_cross_installation():
    async def scenario():
        alpha = await connect("alpha", "agent_alice")
        beta = await connect("beta", "agent_alice")
        lead = await connect("alpha", "lead")
        try:
            before = await beta.fetchval(
                "SELECT payload FROM core.resources WHERE id='project-private'"
            )
            p = await propose(
                alpha, "project-private", {"owner": str(uuid4()), "due": "2026-12-05"}
            )
            await review(lead, p)
            await execute(alpha, p)
            assert (
                await beta.fetchval("SELECT payload FROM core.resources WHERE id='project-private'")
                == before
            )
            assert (
                await beta.fetchval(
                    "SELECT count(*) FROM core.effects WHERE proposal_id=$1", p["id"]
                )
                == 0
            )
        finally:
            await alpha.close()
            await beta.close()
            await lead.close()

    asyncio.run(scenario())
