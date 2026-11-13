from pathlib import Path
from types import ModuleType

import pytest
import retail_fixture.generated as retail_models

from pxos_kernel.ontology import InvalidPackage, InvalidPayload, Registry

RETAIL = Path(__file__).parent / "retail_fixture"


def test_composition_root_registers_package_with_its_models() -> None:
    registry = Registry()
    registered = registry.register(RETAIL, retail_models)

    assert registry.get("retail") is registered
    assert list(registry) == [registered]
    assert set(registered.models) == {"RestockOrder"}
    payload = registered.validate(
        "RestockOrder", {"sku": "A-1", "quantity": 3, "occurred_at": "2026-11-13T10:00:00Z"}
    )
    assert payload == {"sku": "A-1", "quantity": 3, "occurred_at": "2026-11-13T10:00:00Z"}


@pytest.mark.parametrize(
    "payload",
    [
        {"sku": "A-1", "quantity": 0, "occurred_at": "2026-11-13T10:00:00Z"},
        {"sku": "A-1", "occurred_at": "2026-11-13T10:00:00Z"},
        {"sku": "A-1", "quantity": 1, "occurred_at": "2026-11-13T10:00:00Z", "price": 9},
    ],
)
def test_invalid_payload_is_rejected(payload: dict[str, object]) -> None:
    registered = Registry().register(RETAIL, retail_models)
    with pytest.raises(InvalidPayload, match="invalid RestockOrder"):
        registered.validate("RestockOrder", payload)


def test_context_types_take_no_payloads() -> None:
    registered = Registry().register(RETAIL, retail_models)
    with pytest.raises(InvalidPayload, match="not a canonical type"):
        registered.validate("ShelfObservation", {"note": "empty shelf"})


def test_package_is_registered_once() -> None:
    registry = Registry()
    registry.register(RETAIL, retail_models)
    with pytest.raises(InvalidPackage, match="already registered"):
        registry.register(RETAIL, retail_models)


def test_models_must_include_every_canonical_type() -> None:
    with pytest.raises(InvalidPackage, match="generated model RestockOrder not found"):
        Registry().register(RETAIL, ModuleType("empty"))


def test_unknown_package_is_an_error() -> None:
    with pytest.raises(InvalidPackage, match="not registered"):
        Registry().get("retail")


def test_kernel_never_imports_dynamically() -> None:
    """The kernel only knows what it receives at registration (ADR 0003 §1)."""
    source = Path(__file__).parents[1] / "src"
    offenders = [
        str(path.relative_to(source))
        for path in source.rglob("*.py")
        if path.name != "generated.py"
        and any(word in path.read_text(encoding="utf-8") for word in ("importlib", "__import__"))
    ]
    assert offenders == []
