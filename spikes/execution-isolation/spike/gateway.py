"""Harness autenticado por PostgreSQL; não é API/MCP nem gateway de produção."""

import json
from uuid import uuid4

import asyncpg

from spike.generated_projects import Commitment
from spike.generated_support import Ticket

PORTS = {"alpha": 26432, "beta": 26433}
MODELS = {"projects": Commitment, "support": Ticket}


async def connect(installation, actor, *, credential_installation=None):
    credentials = credential_installation or installation
    return await asyncpg.connect(
        host="127.0.0.1",
        port=PORTS[installation],
        database="execution_spike",
        user=actor,
        password=f"local-{credentials}-{actor}",
    )


async def propose(db, target, params):
    resource = await db.fetchrow("SELECT package FROM core.resources WHERE id=$1", target)
    if resource is None:
        raise PermissionError("Recurso indisponível")
    payload = MODELS[resource["package"]].model_validate(params).model_dump(mode="json")
    pid = uuid4()
    checksum = await db.fetchval(
        "SELECT core.propose($1,$2,$3::jsonb)", pid, target, json.dumps(payload)
    )
    return {"id": pid, "digest": checksum, "params": payload}


async def review(db, proposal, decision="approved"):
    await db.execute("SELECT core.review($1,$2,$3)", proposal["id"], proposal["digest"], decision)


async def execute(db, proposal):
    value = await db.fetchval(
        "SELECT core.execute($1,$2,$3::jsonb)",
        proposal["id"],
        proposal["digest"],
        json.dumps(proposal["params"]),
    )
    return json.loads(value)
