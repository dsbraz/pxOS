from datetime import UTC, datetime
from pathlib import Path

from pxos_kernel.ontology.generate import JSON_SCHEMA_FILE, MODELS_FILE, stale_files
from pxos_kernel.ontology.loader import BASE_DIR

RETAIL = Path(__file__).parent / "retail_fixture"


def test_generated_files_match_linkml() -> None:
    """Snapshot: regenerate with `python -m pxos_kernel.ontology.generate <dirs>`."""
    assert stale_files([RETAIL]) == []


def test_generated_files_live_next_to_their_package() -> None:
    for package_dir in (BASE_DIR, RETAIL):
        assert (package_dir / MODELS_FILE).is_file()
        assert (package_dir / JSON_SCHEMA_FILE).is_file()


def test_generated_model_validates_fixture_payload() -> None:
    from retail_fixture.generated import RestockOrder

    order = RestockOrder(sku="A-1", quantity=3, occurred_at=datetime(2026, 11, 13, tzinfo=UTC))
    assert order.quantity == 3
