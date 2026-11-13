"""Acceptance suite: one test per requirement of PRD §4 (ADR 0003 §11).

A requirement not delivered yet is an expected failure (strict), naming the issue that
delivers it. Delivering it means replacing the placeholder with the real test; a
placeholder that starts passing fails the suite.
"""

from datetime import UTC, datetime

import asyncpg
import pytest

from pxos_kernel.identity import session
from pxos_kernel.ontology import Registry
from pxos_kernel.state import Evidence, history, propose, review


def pending(issue: str, scope: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(raises=NotImplementedError, strict=True, reason=f"{issue}: {scope}")


@pending("PXOS-30", "MCP e API como ponto único de acesso")
def test_req_01_same_context_for_people_and_agents() -> None:
    raise NotImplementedError


@pending("PXOS-20", "ingestão automática por eventos")
def test_req_02_capture_without_discipline() -> None:
    raise NotImplementedError


async def test_req_03_every_fact_has_a_source(pool: asyncpg.Pool, registry: Registry) -> None:
    evidence = Evidence(
        source="fixture:shelf-log-2026-11-01",
        quote="Repor 3 unidades do SKU A-1",
        context_ref="fixture:ctx-req-03",
    )
    async with session(pool, "erin") as connection:
        proposal = await propose(
            connection,
            registry.get("retail"),
            "create_restock_order",
            payload={"sku": "A-1", "quantity": 3, "occurred_at": "2026-11-01T09:00:00Z"},
            evidence=evidence,
            valid_from=datetime(2026, 11, 1, tzinfo=UTC),
        )
    async with session(pool, "carla") as connection:
        await review(connection, registry, proposal.id, "approved", digest=proposal.digest)
        (fact,) = await history(connection, proposal.entity_id)
    assert fact.evidence == evidence.as_dict()

    # Without a source the database refuses the proposal, whatever the application does.
    async with session(pool, "erin") as connection:
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """
                INSERT INTO pxos.proposals (
                    package, package_version, package_digest, action, type_name, entity_id,
                    base_revision, operation, valid_from, payload, evidence, digest,
                    author, author_principal
                ) VALUES ($1, $2, $3, 'create_restock_order', 'RestockOrder',
                          gen_random_uuid(), 0, 'assert', now(), '{}', $4, 'x', '', '')
                """,
                proposal.package,
                proposal.package_version,
                proposal.package_digest,
                {"source": "", "quote": "q", "context_ref": "c"},
            )


@pending("PXOS-8", "instalação dedicada; credencial de outra instalação recusada")
def test_req_04_full_isolation_per_client() -> None:
    raise NotImplementedError


@pending("PXOS-9", "atores externos sem acesso ao contexto interno")
def test_req_05_identity_for_people_agents_and_external_actors() -> None:
    raise NotImplementedError


@pending("PXOS-31", "política e autonomia; ação irreversível sempre aprovada")
def test_req_06_action_with_policy_and_approval() -> None:
    raise NotImplementedError


@pending("PXOS-33", "caminho síncrono para ação pré-aprovada")
def test_req_07_action_in_conversation_time() -> None:
    raise NotImplementedError


@pending("PXOS-21", "registros da operação no mesmo estado vivo")
def test_req_08_work_and_operation_data() -> None:
    raise NotImplementedError


@pending("PXOS-37", "job diário de manutenção com fila de revisão")
def test_req_09_automatic_maintenance() -> None:
    raise NotImplementedError


@pending("PXOS-41", "resultado medido contra linha de base auditável")
def test_req_10_measured_and_auditable_result() -> None:
    raise NotImplementedError


@pending("PXOS-10, PXOS-11, PXOS-12", "pseudonimização, residência, consentimento, retenção")
def test_req_11_personal_data_protected() -> None:
    raise NotImplementedError


@pending("PXOS-45", "auditoria de portabilidade no marco do kernel")
def test_req_12_portability() -> None:
    raise NotImplementedError


@pending("PXOS-42", "distribuição de referência feita só de módulos")
def test_req_13_small_and_extensible_kernel() -> None:
    raise NotImplementedError
