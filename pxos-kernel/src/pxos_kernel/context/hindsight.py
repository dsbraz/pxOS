"""Hindsight adapter for the context port (PXOS-53), over its HTTP API.

The bank is configured for custom extraction with the distribution's instructions, and
observations (consolidated summaries) are left out: the kernel reads only the facts
extracted from the document itself. Retaining is synchronous and keyed by document id,
so a replay of an unchanged document keeps its memories as they are.
"""

import os
from typing import Any, Self

import httpx


class HindsightContextStore:
    def __init__(self, base_url: str, bank: str, api_key: str | None = None) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=600)
        self._bank = f"/v1/default/banks/{bank}"

    @classmethod
    def from_environment(cls) -> Self:
        return cls(
            os.environ["PXOS_HINDSIGHT_URL"],
            os.environ.get("PXOS_HINDSIGHT_BANK", "pxos-local"),
            os.environ.get("PXOS_HINDSIGHT_API_KEY"),
        )

    async def retain(self, key: str, text: str, instructions: str) -> None:
        config = await self._client.patch(
            f"{self._bank}/config",
            json={
                "updates": {
                    "retain_extraction_mode": "custom",
                    "retain_custom_instructions": instructions,
                    "enable_observations": False,
                }
            },
        )
        config.raise_for_status()
        retained = await self._client.post(
            f"{self._bank}/memories",
            json={"items": [{"content": text, "document_id": key}], "async": False},
        )
        retained.raise_for_status()

    async def extracted(self, key: str) -> list[str]:
        items: list[dict[str, Any]] = []
        while True:
            response = await self._client.get(
                f"{self._bank}/memories/list",
                params={"document_id": key, "limit": 100, "offset": len(items)},
            )
            if response.status_code == httpx.codes.NOT_FOUND:
                return []
            response.raise_for_status()
            page = response.json()
            items += page["items"]
            if not page["items"] or len(items) >= page["total"]:
                break
        return [i["text"] for i in items if i.get("fact_type") != "observation" and i["text"]]
