"""Context port (PXOS-53): retain content in the context memory and read back what it
extracted. Extraction belongs to the context memory (ADR 0001); the kernel only supplies
the distribution's extraction instructions and validates what comes back.
"""

from collections.abc import Mapping
from typing import Protocol


class ContextStore(Protocol):
    async def retain(self, key: str, text: str, instructions: str) -> None:
        """Retain ``text`` under ``key``; retaining the same key again adds nothing."""

    async def extracted(self, key: str) -> list[str]:
        """The facts extracted from the document under ``key``, as text."""


class FakeContextStore:
    """Deterministic adapter: ``script`` says what extraction yields for each key."""

    def __init__(self, script: Mapping[str, list[str]]) -> None:
        self._script = script
        self._retained: set[str] = set()
        self.retained: list[tuple[str, str]] = []

    async def retain(self, key: str, text: str, instructions: str) -> None:
        self.retained.append((key, instructions))
        self._retained.add(key)

    async def extracted(self, key: str) -> list[str]:
        return list(self._script.get(key, [])) if key in self._retained else []


__all__ = ["ContextStore", "FakeContextStore"]
