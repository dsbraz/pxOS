"""Ingestion and literal-evidence proposals (PXOS-52, PXOS-54).

A connector delivers source documents. Each source version is ingested once: it is kept in
the canonical store, retained in the context memory with the distribution's extraction
instructions, and what the context memory extracted is read back. The distribution's
reader turns an extracted fact into a candidate; the kernel proposes it only when the
quote is literally in the source text it holds, never in text the model returned.
"""

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import asyncpg

from pxos_kernel.context import ContextStore
from pxos_kernel.identity import session
from pxos_kernel.ontology import InvalidPackage, Registry
from pxos_kernel.state import Evidence, InvalidProposal, Proposal, propose


@dataclass(frozen=True)
class SourceDocument:
    source: str
    version: str
    text: str
    occurred_at: datetime

    @property
    def key(self) -> str:
        return f"{self.source}@{self.version}"


class Connector(Protocol):
    def documents(self) -> Iterable[SourceDocument]: ...


class FakeConnector:
    """Delivers the given documents, in order, as a content connector would."""

    def __init__(self, documents: Iterable[SourceDocument]) -> None:
        self._documents = list(documents)

    def documents(self) -> Iterator[SourceDocument]:
        return iter(self._documents)


@dataclass(frozen=True)
class Candidate:
    """What the distribution read from one extracted fact; untrusted until validated."""

    action: str
    payload: dict[str, Any]
    quote: str


Reader = Callable[[str], Candidate | None]

_WHITESPACE = re.compile(r"\s+")


def _collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def quote_in_source(quote: str, source_text: str) -> bool:
    """The quote appears verbatim in the source; only runs of whitespace are normalized."""
    wanted = _collapse(quote)
    return bool(wanted) and wanted in _collapse(source_text)


async def ingest(
    pool: asyncpg.Pool,
    registry: Registry,
    store: ContextStore,
    document: SourceDocument,
    *,
    package: str,
    instructions: str,
    reader: Reader,
    actor: str,
) -> list[Proposal]:
    """Ingest one source version as ``actor``; a replay returns no proposals.

    The source row and the proposals commit together, so a failure leaves nothing behind
    and the same version can be ingested again. Retaining twice is harmless: the context
    memory keys the document by source and version.
    """
    registered = registry.get(package)
    async with session(pool, actor) as connection, connection.transaction():
        status = await connection.execute(
            """
            INSERT INTO pxos.sources (source, version, content) VALUES ($1, $2, $3)
            ON CONFLICT DO NOTHING
            """,
            document.source,
            document.version,
            document.text,
        )
        if status == "INSERT 0 0":
            return []
        await store.retain(document.key, document.text, instructions)
        proposals = []
        for fact in await store.extracted(document.key):
            candidate = reader(fact)
            if candidate is None or not quote_in_source(candidate.quote, document.text):
                continue
            try:
                async with connection.transaction():
                    proposals.append(
                        await propose(
                            connection,
                            registered,
                            candidate.action,
                            payload=candidate.payload,
                            evidence=Evidence(
                                source=document.source,
                                quote=candidate.quote,
                                context_ref=document.key,
                            ),
                            valid_from=document.occurred_at,
                        )
                    )
            except (InvalidPackage, InvalidProposal):
                continue
        return proposals
