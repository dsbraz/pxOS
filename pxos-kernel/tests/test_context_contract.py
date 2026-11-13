"""Context port contract (PXOS-53): one suite for every adapter, so the fake cannot drift.

The Hindsight adapter runs only when PXOS_HINDSIGHT_URL points to a running Hindsight
(local, opt-in: it calls a real model). CI runs the fake.
"""

import os
import re
from pathlib import Path
from uuid import uuid4

import pytest

import pxos_kernel
from pxos_kernel.context import ContextStore, FakeContextStore

TEXT = "Erin: I will restock aisle 3 with 12 boxes of A-1 tomorrow morning.\nCarla: thanks.\n"
INSTRUCTIONS = "Extract every restock promise, with who promised it and the verbatim sentence."
SCRIPTED = ['RESTOCK | who=erin | quote="Erin: I will restock aisle 3 with 12 boxes of A-1"']


ADAPTERS = [
    pytest.param("fake", id="fake"),
    pytest.param(
        "hindsight",
        id="hindsight",
        marks=pytest.mark.skipif(
            not os.environ.get("PXOS_HINDSIGHT_URL"), reason="PXOS_HINDSIGHT_URL not set"
        ),
    ),
]


def store_for(kind: str, key: str) -> ContextStore:
    if kind == "fake":
        return FakeContextStore({key: SCRIPTED})
    from pxos_kernel.context.hindsight import HindsightContextStore

    return HindsightContextStore.from_environment()


@pytest.fixture
def key() -> str:
    return f"fixture:contract/{uuid4()}@1"


@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unknown_document_has_no_facts(kind: str, key: str) -> None:
    assert await store_for(kind, key).extracted(key) == []


@pytest.mark.parametrize("kind", ADAPTERS)
async def test_retained_document_yields_facts_once(kind: str, key: str) -> None:
    store = store_for(kind, key)
    await store.retain(key, TEXT, INSTRUCTIONS)
    facts = await store.extracted(key)
    assert facts and all(isinstance(fact, str) and fact for fact in facts)

    await store.retain(key, TEXT, INSTRUCTIONS)
    assert sorted(await store.extracted(key)) == sorted(facts)


def test_only_the_adapter_talks_to_hindsight() -> None:
    source = Path(pxos_kernel.__file__).parent
    importers = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*.py")
        if re.search(r"^\s*(import|from)\s+(httpx|hindsight_client)\b", path.read_text(), re.M)
    }
    assert importers == {"context/hindsight.py"}
