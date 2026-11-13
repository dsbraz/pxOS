"""Ciclo governado genérico: nenhum tipo ou aprovador de domínio neste módulo."""

import json
import os
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg

from spike.contracts import Package, digest

LOCAL_DSN = "postgresql://spike:local-spike-only@127.0.0.1:25432/ontology_governance_spike"


async def connect():
    connection = await asyncpg.connect(os.getenv("SPIKE_DATABASE_URL", LOCAL_DSN))
    # Schema exclusivo; nenhuma tabela do Hindsight é usada ou alterada.
    await connection.execute("CREATE SCHEMA IF NOT EXISTS ontology_governance_spike")
    await connection.execute("SET search_path TO ontology_governance_spike")
    await connection.execute(Path(__file__).with_name("schema.sql").read_text())
    return connection


def required(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} obrigatório")
    return value


async def propose(db, package, entity, payload, *, author, evidence, valid_from, base_revision=0):
    domain = Package(package)
    required(entity, "entity")
    required(author, "author")
    if type(base_revision) is not int or base_revision < 0:
        raise ValueError("base_revision deve ser inteiro não negativo")
    if set(evidence) != {"source", "quote", "context_ref"}:
        raise ValueError("Evidência exige source, quote e context_ref")
    for field, value in evidence.items():
        required(value, field)
    body = {
        "package": package,
        "entity": entity,
        "schema_version": domain.manifest["version"],
        "schema_digest": domain.fingerprint,
        "payload": domain.validate(payload),
        "author": author,
        "evidence": evidence,
        "valid_from": date.fromisoformat(valid_from).isoformat(),
        "base_revision": base_revision,
    }
    proposal_id = uuid4()
    checksum = digest(body)
    await db.execute(
        "INSERT INTO proposals(id,package,entity,body,digest) VALUES($1,$2,$3,$4::jsonb,$5)",
        proposal_id,
        package,
        entity,
        json.dumps(body),
        checksum,
    )
    return {"id": str(proposal_id), "digest": checksum, "body": body}


async def review(db, proposal_id, expected_digest, *, reviewer, decision, reason):
    if decision not in {"approved", "rejected"}:
        raise ValueError("Decisão inválida")
    required(reason, "reason")
    async with db.transaction():
        proposal = await db.fetchrow(
            "SELECT * FROM proposals WHERE id=$1 FOR UPDATE", UUID(proposal_id)
        )
        if proposal is None:
            raise ValueError("Proposta inexistente")
        body = json.loads(proposal["body"])
        domain = Package(proposal["package"])
        if expected_digest != proposal["digest"] or digest(body) != expected_digest:
            raise ValueError("Aprovação não corresponde ao conteúdo revisado")
        if domain.fingerprint != body["schema_digest"]:
            raise ValueError("Pacote mudou; emitir nova proposta")
        if reviewer not in domain.manifest["approvers"] or reviewer == body["author"]:
            raise PermissionError("Revisor não autorizado")
        previous = await db.fetchrow("SELECT * FROM reviews WHERE proposal_id=$1", proposal["id"])
        if previous:
            if (previous["reviewer"], previous["decision"], previous["reason"]) == (
                reviewer,
                decision,
                reason,
            ):
                return  # Reentrega da mesma decisão é idempotente.
            raise ValueError("Proposta já revisada")
        if decision == "approved":
            # Serializa decisões sobre a mesma entidade, incluindo a primeira publicação.
            await db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                json.dumps([proposal["package"], proposal["entity"]]),
            )
            revision = await db.fetchval(
                "SELECT COALESCE(MAX(revision),0) FROM facts WHERE package=$1 AND entity=$2",
                proposal["package"],
                proposal["entity"],
            )
            if revision != body["base_revision"]:
                raise ValueError("Proposta obsoleta; revisar novamente sobre a versão atual")
            domain.validate(body["payload"])
        await db.execute(
            "INSERT INTO reviews(proposal_id,reviewer,decision,reason) VALUES($1,$2,$3,$4)",
            proposal["id"],
            reviewer,
            decision,
            reason,
        )
        if decision == "approved":
            await db.execute(
                "INSERT INTO facts(package,entity,revision,proposal_id) VALUES($1,$2,$3,$4)",
                proposal["package"],
                proposal["entity"],
                revision + 1,
                proposal["id"],
            )


async def history(db, package, entity):
    rows = await db.fetch(
        """SELECT f.revision, f.recorded_at, p.body, p.digest, p.id AS proposal_id,
                  r.reviewer, r.reason, p.proposed_at
           FROM facts f JOIN proposals p ON p.id=f.proposal_id
           JOIN reviews r ON r.proposal_id=p.id
           WHERE f.package=$1 AND f.entity=$2 ORDER BY f.revision""",
        package,
        entity,
    )
    return [dict(row) | {"body": json.loads(row["body"])} for row in rows]


async def as_of(db, package, entity, *, valid_on, known_at):
    valid_date = date.fromisoformat(valid_on)
    if known_at.tzinfo is None:
        raise ValueError("known_at exige timezone")
    rows = await history(db, package, entity)
    applicable = [
        row
        for row in rows
        if row["recorded_at"] <= known_at
        and date.fromisoformat(row["body"]["valid_from"]) <= valid_date
    ]
    # Snapshot a partir de valid_from; empates de data usam a última correção conhecida.
    return max(
        applicable, key=lambda row: (row["body"]["valid_from"], row["revision"]), default=None
    )
