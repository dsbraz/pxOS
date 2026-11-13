from pathlib import Path
from typing import Any

import pytest
import yaml
from linkml_runtime.utils.schemaview import SchemaView

from pxos_kernel.ontology import (
    BASE_SCHEMA,
    ActionType,
    InvalidPackage,
    Kind,
    load_package,
)
from pxos_kernel.ontology.loader import class_kind, is_compatible

RETAIL = Path(__file__).parent / "fixtures" / "retail"


def write_package(
    tmp_path: Path, schema: dict[str, Any], actions: list[dict[str, Any]]
) -> tuple[Path, Path]:
    schema_path = tmp_path / "ontology.yaml"
    actions_path = tmp_path / "actions.yaml"
    schema_path.write_text(yaml.safe_dump(schema, allow_unicode=True), encoding="utf-8")
    actions_path.write_text(yaml.safe_dump(actions), encoding="utf-8")
    return schema_path, actions_path


def retail() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    schema = yaml.safe_load((RETAIL / "ontology.yaml").read_text(encoding="utf-8"))
    actions = yaml.safe_load((RETAIL / "actions.yaml").read_text(encoding="utf-8"))
    return schema, actions


def test_base_has_minimal_types_with_kind_and_portuguese_labels() -> None:
    base = SchemaView(str(BASE_SCHEMA))
    assert set(base.all_classes()) == {"Organization", "Actor", "Role", "Event", "Evidence"}
    assert base.schema.version
    for name in base.all_classes():
        assert class_kind(base, name, "pxos_base") in Kind
        assert base.get_class(name).title


def test_fixture_package_extends_base() -> None:
    package = load_package(RETAIL / "ontology.yaml", RETAIL / "actions.yaml")

    assert package.name == "retail"
    assert package.version == "0.1.0"
    assert package.kinds == {"RestockOrder": Kind.CANONICAL, "ShelfObservation": Kind.CONTEXT}
    assert package.actions == (
        ActionType(
            name="create_restock_order",
            creates="RestockOrder",
            approver="store-manager",
            reversible=True,
            rule_parameters=("quantity",),
        ),
    )
    assert "occurred_at" in package.schema.class_slots("RestockOrder")


def test_package_must_import_base(tmp_path: Path) -> None:
    schema, actions = retail()
    schema["imports"] = ["linkml:types"]
    schema["classes"]["RestockOrder"].pop("is_a")
    with pytest.raises(InvalidPackage, match="must import pxos_base"):
        load_package(*write_package(tmp_path, schema, actions))


def test_package_must_declare_kind_for_every_type(tmp_path: Path) -> None:
    schema, actions = retail()
    del schema["classes"]["ShelfObservation"]["annotations"]
    with pytest.raises(InvalidPackage, match="ShelfObservation must declare pxos.kind"):
        load_package(*write_package(tmp_path, schema, actions))


def test_package_cannot_redefine_base_type(tmp_path: Path) -> None:
    schema, actions = retail()
    schema["classes"]["Role"] = {"annotations": {"pxos.kind": "canonical"}}
    with pytest.raises(InvalidPackage, match="redefines base types"):
        load_package(*write_package(tmp_path, schema, actions))


def test_package_built_for_other_base_version_is_rejected(tmp_path: Path) -> None:
    schema, actions = retail()
    schema["annotations"]["pxos.base_version"] = "0.2.0"
    with pytest.raises(InvalidPackage, match="built for base 0.2.0"):
        load_package(*write_package(tmp_path, schema, actions))


@pytest.mark.parametrize(
    ("declared", "available", "compatible"),
    [
        ("0.1.0", "0.1.3", True),
        ("0.1.0", "0.2.0", False),
        ("1.0.0", "1.4.0", True),
        ("1.0.0", "2.0.0", False),
    ],
)
def test_layer_version_compatibility(declared: str, available: str, compatible: bool) -> None:
    assert is_compatible(declared, available) is compatible


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"approver": None}, "invalid action type"),
        ({"reversible": "maybe"}, "invalid action type"),
        ({"autonomy": "full"}, "invalid action type"),
        ({"creates": "ShelfObservation"}, "must create a canonical type"),
        ({"creates": "Role"}, "must create a canonical type"),
        ({"rule_parameters": ["price"]}, r"rule parameters \['price'\] unknown"),
    ],
)
def test_action_type_must_follow_metamodel(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    schema, actions = retail()
    action = {**actions[0], **change}
    action = {key: value for key, value in action.items() if value is not None}
    with pytest.raises(InvalidPackage, match=message):
        load_package(*write_package(tmp_path, schema, [action]))


def test_action_type_names_are_unique(tmp_path: Path) -> None:
    schema, actions = retail()
    with pytest.raises(InvalidPackage, match="duplicated action type names"):
        load_package(*write_package(tmp_path, schema, actions * 2))
