"""Channel port and review cards (PXOS-55).

A created proposal becomes a card for each actor who holds the action's approver role,
except its author and whoever the author acts for. The card is read in the recipient's
session, so RLS decides whether they see it at all. Delivery is keyed by proposal: a
redelivered event replaces the same card. Approving a card is a review by the recipient
on exactly the digest the card showed.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import asyncpg

from pxos_kernel.identity import session
from pxos_kernel.ontology import Registry
from pxos_kernel.state import (
    Decision,
    Event,
    Handler,
    InvalidProposal,
    Review,
    get_proposal,
    review,
)


@dataclass(frozen=True)
class Card:
    proposal_id: UUID
    recipient: str
    package: str
    action: str
    title: str
    payload: dict[str, Any]
    quote: str
    source: str
    digest: str


class Channel(Protocol):
    async def deliver_card(self, card: Card) -> None:
        """Show ``card`` to its recipient; delivering the same card again replaces it."""


class FakeChannel:
    """Reference channel: keeps each recipient's cards by proposal."""

    def __init__(self) -> None:
        self.cards: dict[str, dict[UUID, Card]] = defaultdict(dict)

    async def deliver_card(self, card: Card) -> None:
        self.cards[card.recipient][card.proposal_id] = card


def route_cards(pool: asyncpg.Pool, registry: Registry, channel: Channel) -> Handler:
    """Handler for ``proposal.created`` that delivers a card to each eligible approver."""

    async def route(event: Event) -> None:
        proposal_id = UUID(event.payload["proposal_id"])
        registered = registry.get(event.payload["package"])
        async with pool.acquire() as connection:
            approver = registered.package.action(event.payload["action"]).approver
            candidates = await connection.fetch(
                "SELECT actor_id FROM pxos.actor_roles WHERE role = $1 ORDER BY actor_id",
                approver,
            )
        for row in candidates:
            recipient = row["actor_id"]
            async with session(pool, recipient) as connection:
                try:
                    proposal = await get_proposal(connection, proposal_id)
                except InvalidProposal:
                    continue  # the recipient cannot read this proposal
            if recipient in {proposal.author, proposal.author_principal}:
                continue
            await channel.deliver_card(
                Card(
                    proposal_id=proposal.id,
                    recipient=recipient,
                    package=proposal.package,
                    action=proposal.action,
                    title=registered.package.schema.get_class(proposal.type_name).title
                    or proposal.type_name,
                    payload=proposal.payload,
                    quote=proposal.evidence["quote"],
                    source=proposal.evidence["source"],
                    digest=proposal.digest,
                )
            )

    return route


async def decide(
    pool: asyncpg.Pool,
    registry: Registry,
    actor: str,
    card: Card,
    decision: Decision,
    *,
    reason: str | None = None,
) -> Review:
    """Record ``actor``'s decision on the proposal exactly as ``card`` showed it."""
    async with session(pool, actor) as connection:
        return await review(
            connection, registry, card.proposal_id, decision, digest=card.digest, reason=reason
        )
