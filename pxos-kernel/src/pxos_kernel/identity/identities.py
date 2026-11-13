"""Fixed identities loaded from configuration (PXOS-51).

People and agents are actors with roles; a delegation lets an agent act on behalf of a
person with only that person's roles. The owner connection writes them at bootstrap;
the application role can only read them.
"""

from pathlib import Path
from typing import Literal

import asyncpg
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from pxos_kernel.errors import PxosError


class InvalidIdentities(PxosError):
    """The identity configuration is inconsistent."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Actor(_Strict):
    id: str
    kind: Literal["internal_person", "agent"]
    name: str
    roles: tuple[str, ...] = ()


class Delegation(_Strict):
    agent: str
    person: str


class Identities(_Strict):
    actors: tuple[Actor, ...]
    delegations: tuple[Delegation, ...] = ()


def read_identities(path: Path) -> Identities:
    try:
        identities = Identities.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as error:
        raise InvalidIdentities(f"{path}: {error}") from None
    kinds = {actor.id: actor.kind for actor in identities.actors}
    if len(kinds) != len(identities.actors):
        raise InvalidIdentities(f"{path}: duplicated actor ids")
    for delegation in identities.delegations:
        if kinds.get(delegation.agent) != "agent":
            raise InvalidIdentities(f"{path}: {delegation.agent} is not an agent")
        if kinds.get(delegation.person) != "internal_person":
            raise InvalidIdentities(f"{path}: {delegation.person} is not a person")
    return identities


async def install_identities(owner: asyncpg.Connection, identities: Identities) -> None:
    """Upsert actors and replace roles and delegations, in one transaction."""
    async with owner.transaction():
        await owner.executemany(
            """
            INSERT INTO pxos.actors (id, kind, name) VALUES ($1, $2, $3)
            ON CONFLICT (id) DO UPDATE SET kind = EXCLUDED.kind, name = EXCLUDED.name
            """,
            [(actor.id, actor.kind, actor.name) for actor in identities.actors],
        )
        await owner.execute("DELETE FROM pxos.actor_roles")
        await owner.executemany(
            "INSERT INTO pxos.actor_roles (actor_id, role) VALUES ($1, $2)",
            [(actor.id, role) for actor in identities.actors for role in actor.roles],
        )
        await owner.execute("DELETE FROM pxos.delegations")
        await owner.executemany(
            "INSERT INTO pxos.delegations (agent_id, person_id) VALUES ($1, $2)",
            [(item.agent, item.person) for item in identities.delegations],
        )
