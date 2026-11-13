from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import retail_fixture.generated as retail_models
import yaml

from brq_at_work.composition import IDENTITIES, bootstrap, build_registry
from db_testing import Database, create_test_database
from pxos_kernel.ontology import Registry
from pxos_kernel.state import create_pool

RETAIL = Path(__file__).parents[2] / "pxos-kernel" / "tests" / "retail_fixture"


@pytest.fixture(scope="session")
def registry() -> Registry:
    """The BRQ@work composition plus the kernel's retail fixture, to run the same cycle."""
    registry = build_registry()
    registry.register(RETAIL, retail_models)
    return registry


@pytest.fixture(scope="session")
def database(registry: Registry, tmp_path_factory: pytest.TempPathFactory) -> Database:
    brq = yaml.safe_load(IDENTITIES.read_text(encoding="utf-8"))
    retail = yaml.safe_load((RETAIL / "identities.yaml").read_text(encoding="utf-8"))
    identities = tmp_path_factory.mktemp("identities") / "identities.yaml"
    identities.write_text(
        yaml.safe_dump(
            {
                "actors": brq["actors"] + retail["actors"],
                "delegations": brq["delegations"] + retail["delegations"],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    database = create_test_database("pxos_test_brq")
    bootstrap(database.owner_dsn, registry, identities)
    return database


@pytest.fixture
async def pool(database: Database) -> AsyncIterator[asyncpg.Pool]:
    pool = await create_pool(database.app_dsn)
    yield pool
    await pool.close()
