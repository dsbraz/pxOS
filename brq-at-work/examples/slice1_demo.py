"""Demo da fatia 1: ciclo canônico de um compromisso da BRQ@work.

Recria o banco local ``pxos_demo`` no Postgres do Compose e roda proposta, recusas,
aprovação, correção retroativa e leitura em duas datas. Na raiz do repositório:

    docker compose up -d --wait
    PYTHONPATH=. uv run python brq-at-work/examples/slice1_demo.py
"""

import asyncio
from datetime import UTC, datetime

from brq_at_work.composition import bootstrap, build_registry
from db_testing import create_test_database
from pxos_kernel.identity import session
from pxos_kernel.state import (
    Evidence,
    NotApprover,
    SelfApproval,
    as_of,
    create_pool,
    history,
    propose,
    review,
)

registry = build_registry()
db = create_test_database("pxos_demo")
bootstrap(db.owner_dsn, registry)
print("banco:", db.app_dsn)

EVIDENCE = Evidence(
    source="fixture:transcript/2026-11-10-kickoff",
    quote="Bruno: eu entrego o protótipo até o dia 28.",
    context_ref="fixture:context/kickoff-0001",
)
COMMITMENT = {
    "description": "Entregar o protótipo",
    "owner": "bruno",
    "due_date": "2026-11-28",
    "work_stream": "onboarding-app",
}
NOV10, NOV15 = datetime(2026, 11, 10, tzinfo=UTC), datetime(2026, 11, 15, tzinfo=UTC)


async def main() -> None:
    pool = await create_pool(db.app_dsn)
    work = registry.get("work_context")

    async with session(pool, "bruno") as c:
        p = await propose(
            c, work, "create_commitment", payload=COMMITMENT, evidence=EVIDENCE, valid_from=NOV10
        )
    print("1. Bruno propôs:", p.payload, "| digest", p.digest[:12])

    for who, err in (("bruno", SelfApproval), ("celia", NotApprover)):
        try:
            async with session(pool, who) as c:
                await review(c, registry, p.id, "approved", digest=p.digest)
        except err as e:
            print(f"2. {who} tentou aprovar e foi recusado: {type(e).__name__}")

    async with session(pool, "ana") as c:
        await review(c, registry, p.id, "approved", digest=p.digest)
    print("3. Ana (gerente de projeto) aprovou")

    async with session(pool, "bruno") as c:
        fix = await propose(
            c,
            work,
            "create_commitment",
            payload={**COMMITMENT, "due_date": "2026-11-21"},
            evidence=EVIDENCE,
            valid_from=NOV10,
            entity_id=p.entity_id,
            base_revision=1,
        )
    async with session(pool, "ana") as c:
        await review(c, registry, fix.id, "approved", digest=fix.digest)
    print("4. Correção retroativa do prazo aprovada")

    async with session(pool, "ana") as c:
        v1, v2 = await history(c, p.entity_id)
        before = await as_of(c, p.entity_id, valid_at=NOV15, known_at=v1.known_at)
        after = await as_of(c, p.entity_id, valid_at=NOV15, known_at=v2.known_at)
    assert before is not None and after is not None
    print("5. Prazo válido em 15/11, como se sabia antes da correção:", before.payload["due_date"])
    print("   Prazo válido em 15/11, como se sabe agora:", after.payload["due_date"])
    print("   Histórico:", [(f.revision, f.payload["due_date"]) for f in (v1, v2)])
    print("   entity_id:", p.entity_id)
    await pool.close()


asyncio.run(main())
