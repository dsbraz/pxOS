"""Exit criterion of slice 2 (PXOS-56): from a synthetic transcript to a commitment approved
on a review card, with the literal quote as evidence.

In CI the context store is the kernel's fake: its scripted extraction stands in for what
Hindsight returns under the BRQ@work extraction instructions. The real run is opt-in: with
PXOS_HINDSIGHT_URL set, the same test runs against Hindsight and a real model.
"""

import os
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest

from brq_at_work.scribe import INSTRUCTIONS, read_commitment
from db_testing import Database
from pxos_kernel.channel import FakeChannel, decide, route_cards
from pxos_kernel.context import ContextStore, FakeContextStore
from pxos_kernel.identity import session
from pxos_kernel.ingestion import FakeConnector, SourceDocument, ingest
from pxos_kernel.ontology import Registry
from pxos_kernel.state import create_pool, history, publish

QUOTE = "Bruno: fechado, eu entrego o protótipo do onboarding até sexta, dia 28."

TRANSCRIPT = f"""\
Ana: bom dia, vamos repassar o status do app de onboarding.
{QUOTE}
Célia: eu vejo com o time de dados se a carga de teste fica pronta.
Ana: ótimo, obrigada.
"""

REAL = (
    "COMPROMISSO | dono=bruno | prazo=2026-11-28 | frente=onboarding-app"
    f' | descrição=Entregar o protótipo do onboarding | trecho="{QUOTE}"'
)
# Nobody said this; the model made it up.
INVENTED = (
    "COMPROMISSO | dono=celia | prazo=2026-11-20 | frente=onboarding-app"
    ' | descrição=Publicar a carga de teste | trecho="Célia: eu publico a carga de teste dia 20."'
)
# Close to what was said, but not what was said.
PARAPHRASE = (
    "COMPROMISSO | dono=celia | prazo=2026-11-28 | frente=onboarding-app"
    " | descrição=Verificar a carga de teste"
    ' | trecho="Célia: vou ver com o time de dados se a carga de teste fica pronta."'
)

STORES = [
    pytest.param("fake", id="fake"),
    pytest.param(
        "hindsight",
        id="hindsight",
        marks=pytest.mark.skipif(
            not os.environ.get("PXOS_HINDSIGHT_URL"), reason="PXOS_HINDSIGHT_URL not set"
        ),
    ),
]


def store_for(kind: str, document: SourceDocument) -> ContextStore:
    if kind == "fake":
        return FakeContextStore({document.key: [REAL, INVENTED, PARAPHRASE]})
    from pxos_kernel.context.hindsight import HindsightContextStore

    return HindsightContextStore.from_environment()


@pytest.mark.parametrize("kind", STORES)
async def test_transcript_becomes_a_commitment_approved_on_a_card(
    database: Database, pool: asyncpg.Pool, registry: Registry, kind: str
) -> None:
    document = SourceDocument(
        source=f"fixture:transcript/2026-11-12-status/{uuid4()}",
        version="1",
        text=TRANSCRIPT,
        occurred_at=datetime(2026, 11, 12, 14, tzinfo=UTC),
    )
    connector = FakeConnector([document])
    store = store_for(kind, document)
    channel = FakeChannel()
    publisher = await create_pool(database.publisher_dsn)
    try:
        await publish(publisher, {})  # events left by earlier tests are not ours
        # 1-4: transcript in, retained, and only the commitment with a literal quote proposed.
        proposals = []
        for received in connector.documents():
            proposals += await ingest(
                pool,
                registry,
                store,
                received,
                package="work_context",
                instructions=INSTRUCTIONS,
                reader=read_commitment,
                actor="scribe-agent",
            )
        if isinstance(store, FakeContextStore):
            assert store.retained == [(document.key, INSTRUCTIONS)]
        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal.author == "scribe-agent"
        assert proposal.evidence["quote"] == QUOTE
        assert proposal.payload["owner"] == "bruno"

        # 5: the card reaches the approver role only, with the quote.
        await publish(publisher, {"proposal.created": route_cards(pool, registry, channel)})
        assert set(channel.cards) == {"ana"}
        [card] = channel.cards["ana"].values()
        assert card.proposal_id == proposal.id
        assert card.quote == QUOTE
        assert card.digest == proposal.digest
        assert card.title == "Compromisso"

        # 6: approving on the card records the fact with the quote as evidence.
        await decide(pool, registry, "ana", card, "approved")
        async with session(pool, "celia") as connection:
            [fact] = await history(connection, proposal.entity_id)
        assert fact.evidence["quote"] == QUOTE
        assert fact.payload == proposal.payload

        # 7: replaying the transcript creates no proposal and no card.
        again = await ingest(
            pool,
            registry,
            store,
            document,
            package="work_context",
            instructions=INSTRUCTIONS,
            reader=read_commitment,
            actor="scribe-agent",
        )
        assert again == []
        await publish(publisher, {"proposal.created": route_cards(pool, registry, channel)})
        assert len(channel.cards["ana"]) == 1
    finally:
        await publisher.close()
