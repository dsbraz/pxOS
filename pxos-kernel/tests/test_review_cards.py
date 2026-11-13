"""Review cards on a channel (PXOS-55).

A created proposal becomes a card for whoever holds the action's approver role and can
read the type, never for its author or whoever the author acts for. The card is built in
the recipient's session; approving it is a review by the recipient on the card's digest.
"""

from dataclasses import replace
from datetime import UTC, datetime

import asyncpg
import pytest

from pxos_kernel.channel import FakeChannel, decide, route_cards
from pxos_kernel.identity import session
from pxos_kernel.ontology import Registry
from pxos_kernel.state import (
    DecisionFinal,
    DigestMismatch,
    Event,
    Evidence,
    Proposal,
    history,
    propose,
)

EVIDENCE = Evidence(source="fixture:shelf-log", quote="restock 5", context_ref="fixture:ctx-1")


async def proposed(
    pool: asyncpg.Pool, registry: Registry, actor: str, on_behalf_of: str | None = None
) -> Proposal:
    async with session(pool, actor, on_behalf_of) as connection:
        return await propose(
            connection,
            registry.get("retail"),
            "create_restock_order",
            payload={"sku": "C-3", "quantity": 5, "occurred_at": "2026-11-01T09:00:00Z"},
            evidence=EVIDENCE,
            valid_from=datetime(2026, 11, 1, tzinfo=UTC),
        )


def created(proposal: Proposal) -> Event:
    return Event(
        id=1,
        event_type="proposal.created",
        entity_id=proposal.entity_id,
        payload={
            "proposal_id": str(proposal.id),
            "package": "retail",
            "action": "create_restock_order",
        },
        created_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    ("actor", "on_behalf_of", "recipients"),
    [
        ("erin", None, {"carla", "diego"}),
        ("carla", None, {"diego"}),
        ("restock-agent", "carla", {"diego"}),
    ],
)
async def test_card_goes_to_approvers_other_than_the_author(
    pool: asyncpg.Pool,
    registry: Registry,
    actor: str,
    on_behalf_of: str | None,
    recipients: set[str],
) -> None:
    proposal = await proposed(pool, registry, actor, on_behalf_of)
    channel = FakeChannel()
    await route_cards(pool, registry, channel)(created(proposal))
    assert set(channel.cards) == recipients
    for cards in channel.cards.values():
        card = cards[proposal.id]
        assert card.title == "Pedido de reposição"
        assert card.quote == "restock 5"
        assert card.payload == proposal.payload
        assert card.digest == proposal.digest


async def test_redelivery_does_not_duplicate_cards(pool: asyncpg.Pool, registry: Registry) -> None:
    proposal = await proposed(pool, registry, "erin")
    channel = FakeChannel()
    route = route_cards(pool, registry, channel)
    await route(created(proposal))
    await route(created(proposal))
    assert {name: len(cards) for name, cards in channel.cards.items()} == {"carla": 1, "diego": 1}


async def test_approving_a_card_records_the_fact(pool: asyncpg.Pool, registry: Registry) -> None:
    proposal = await proposed(pool, registry, "erin")
    channel = FakeChannel()
    await route_cards(pool, registry, channel)(created(proposal))

    review = await decide(pool, registry, "carla", channel.cards["carla"][proposal.id], "approved")

    assert review.reviewer == "carla"
    async with session(pool, "erin") as connection:
        [fact] = await history(connection, proposal.entity_id)
    assert fact.proposal_id == proposal.id


async def test_stale_card_and_late_contrary_decision_are_refused(
    pool: asyncpg.Pool, registry: Registry
) -> None:
    proposal = await proposed(pool, registry, "erin")
    channel = FakeChannel()
    await route_cards(pool, registry, channel)(created(proposal))
    carla_card = channel.cards["carla"][proposal.id]

    with pytest.raises(DigestMismatch):
        await decide(pool, registry, "carla", replace(carla_card, digest="0" * 64), "approved")

    await decide(pool, registry, "carla", carla_card, "approved")
    with pytest.raises(DecisionFinal):
        await decide(
            pool,
            registry,
            "diego",
            channel.cards["diego"][proposal.id],
            "rejected",
            reason="quantidade errada",
        )
