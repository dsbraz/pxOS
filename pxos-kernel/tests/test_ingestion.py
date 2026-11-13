"""Ingestion and literal-evidence proposals (PXOS-52, PXOS-54).

A source version is ingested once. What the context memory extracted becomes a proposal
only when its quote is literally in the source text; whitespace is the only thing
normalized. Model output is untrusted: a candidate that fails the schema is dropped.
"""

import re
from datetime import UTC, datetime

import asyncpg
import pytest

from db_testing import Database
from pxos_kernel.context import FakeContextStore
from pxos_kernel.ingestion import (
    Candidate,
    FakeConnector,
    SourceDocument,
    ingest,
    quote_in_source,
)
from pxos_kernel.ontology import Registry

LOG = "Erin: I will restock aisle 3 with 12 boxes of A-1 tomorrow morning.\nCarla: thanks.\n"
INSTRUCTIONS = 'Extract restock promises as: RESTOCK | sku=<sku> | qty=<n> | quote="<verbatim>"'
FACT = re.compile(r'RESTOCK \| sku=(?P<sku>[^|]+) \| qty=(?P<qty>[^|]+) \| quote="(?P<quote>.*)"')


def read_restock(fact: str) -> Candidate | None:
    match = FACT.fullmatch(fact)
    if match is None:
        return None
    return Candidate(
        action="create_restock_order",
        payload={
            "sku": match["sku"],
            "quantity": int(match["qty"]) if match["qty"].isdigit() else match["qty"],
            "occurred_at": "2026-11-01T09:00:00Z",
        },
        quote=match["quote"],
    )


def restock(quote: str, sku: str = "A-1", qty: str = "12") -> str:
    return f'RESTOCK | sku={sku} | qty={qty} | quote="{quote}"'


def document(name: str, text: str = LOG) -> SourceDocument:
    return SourceDocument(
        source=f"fixture:shelf-log/{name}",
        version="1",
        text=text,
        occurred_at=datetime(2026, 11, 1, 9, tzinfo=UTC),
    )


async def run(
    pool: asyncpg.Pool, registry: Registry, store: FakeContextStore, doc: SourceDocument
) -> list[str]:
    proposals = await ingest(
        pool,
        registry,
        store,
        doc,
        package="retail",
        instructions=INSTRUCTIONS,
        reader=read_restock,
        actor="restock-agent",
    )
    return [p.evidence["quote"] for p in proposals]


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("Erin: I will restock aisle 3 with 12 boxes of A-1", True),
        ("Erin:  I will restock\naisle 3", True),
        ("Erin: I'll restock aisle 3 with 12 boxes of A-1", False),
        ("erin: i will restock aisle 3", False),
        ("Erin: I will restock aisle 3, with 12 boxes", False),
        ("   ", False),
        ("", False),
    ],
)
def test_quote_must_be_literally_in_the_source(quote: str, expected: bool) -> None:
    assert quote_in_source(quote, LOG) is expected


async def test_only_candidates_with_a_literal_quote_become_proposals(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    doc = document("literal")
    other = "Gina: I will restock aisle 9 with 4 boxes of B-2."
    store = FakeContextStore(
        {
            doc.key: [
                restock("Erin: I will restock aisle 3 with 12 boxes of A-1"),
                restock("Erin: I'll restock aisle 3 with 12 boxes of A-1"),  # paraphrase
                restock(other, sku="B-2", qty="4"),  # another document
                restock("Erin: I will restock aisle 3", qty="zero"),  # fails the schema
                restock("Erin: I will restock aisle 3", qty="0"),  # fails the schema
                "not a restock fact at all",
            ]
        }
    )
    quotes = await run(pool, registry, store, doc)
    assert quotes == ["Erin: I will restock aisle 3 with 12 boxes of A-1"]
    assert store.retained == [(doc.key, INSTRUCTIONS)]


async def test_replay_of_a_source_version_creates_nothing(
    database: Database, pool: asyncpg.Pool, registry: Registry
) -> None:
    doc = document("replay")
    store = FakeContextStore({doc.key: [restock("Erin: I will restock aisle 3")]})
    connector = FakeConnector([doc, doc])

    created = [await run(pool, registry, store, d) for d in connector.documents()]

    assert created == [["Erin: I will restock aisle 3"], []]
    owner = await asyncpg.connect(database.owner_dsn)
    try:
        rows = await owner.fetch(
            "SELECT ingested_by FROM pxos.sources WHERE source = $1", doc.source
        )
    finally:
        await owner.close()
    assert [r["ingested_by"] for r in rows] == ["restock-agent"]


async def test_failed_ingestion_leaves_no_trace_and_can_be_retried(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    doc = document("retry")
    store = FakeContextStore({doc.key: [restock("Erin: I will restock aisle 3")]})

    def broken(fact: str) -> Candidate | None:
        raise RuntimeError("reader crashed")

    with pytest.raises(RuntimeError):
        await ingest(
            pool,
            registry,
            store,
            doc,
            package="retail",
            instructions=INSTRUCTIONS,
            reader=broken,
            actor="restock-agent",
        )
    assert await run(pool, registry, store, doc) == ["Erin: I will restock aisle 3"]


async def test_application_cannot_read_ingested_sources(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as connection:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await connection.fetch("SELECT content FROM pxos.sources")
