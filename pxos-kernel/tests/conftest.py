import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import retail_fixture.generated as retail_models

from db_testing import Database, create_test_database
from pxos_kernel.identity import install_identities, read_identities
from pxos_kernel.ontology import Registry
from pxos_kernel.state import create_pool, install_packages

RETAIL = Path(__file__).parent / "retail_fixture"


@pytest.fixture(scope="session")
def registry() -> Registry:
    registry = Registry()
    registry.register(RETAIL, retail_models)
    return registry


@pytest.fixture(scope="session")
def database(registry: Registry) -> Database:
    database = create_test_database("pxos_test_kernel")

    async def bootstrap() -> None:
        owner = await asyncpg.connect(database.owner_dsn)
        try:
            await install_identities(owner, read_identities(RETAIL / "identities.yaml"))
            await install_packages(owner, registry)
        finally:
            await owner.close()

    asyncio.run(bootstrap())
    return database


@pytest.fixture
async def pool(database: Database) -> AsyncIterator[asyncpg.Pool]:
    pool = await create_pool(database.app_dsn)
    yield pool
    await pool.close()
