"""Verifica o backend real e a proteção HTTP sem mostrar credenciais."""

import asyncio
import json

import asyncpg
import httpx

from spike.settings import API_URL, ROOT, configure, keys


async def inspect_database(dsn):
    connection = await asyncpg.connect(dsn)
    try:
        return {
            "version": await connection.fetchval("SELECT version()"),
            "alloydb_settings": await connection.fetchval(
                "SELECT count(*) FROM pg_settings WHERE name LIKE 'alloydb.%'"
            ),
            "database": await connection.fetchval("SELECT current_database()"),
            "extensions": [
                dict(r)
                for r in await connection.fetch(
                    "SELECT extname, extversion FROM pg_extension ORDER BY extname"
                )
            ],
            "tables": await connection.fetchval(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
            ),
        }
    finally:
        await connection.close()


def main():
    dsn = configure()
    result = asyncio.run(inspect_database(dsn))
    with httpx.Client(base_url=API_URL, timeout=60) as client:
        result["health"] = client.get("/health").json()
        route = "/v1/default/banks/pxos-hs-auth-check/memories/list"
        result["unauthenticated_status"] = client.get(route).status_code
        result["invalid_token_status"] = client.get(
            route, headers={"Authorization": "Bearer invalid-test"}
        ).status_code
        assert result["unauthenticated_status"] in (401, 403)
        assert result["invalid_token_status"] in (401, 403)
        assert result["database"] == "hindsight_spike"
        assert result["alloydb_settings"] > 0
        metrics = client.get("/metrics", headers={"Authorization": "Bearer " + keys()["admin"]})
        metrics.raise_for_status()
        (ROOT / "runs/metrics-before.txt").write_text(metrics.text)
    (ROOT / "runs/doctor.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
