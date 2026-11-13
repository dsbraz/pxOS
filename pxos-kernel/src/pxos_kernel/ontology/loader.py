"""Load a domain package on top of the base ontology and check its layer rules.

A package is a LinkML schema that imports ``pxos_base`` plus an ``actions.yaml`` file
validated against the action metamodel. The kernel only knows what the package declares.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from linkml.validator import validate
from linkml_runtime.utils.schemaview import SchemaView

from pxos_kernel.errors import PxosError

ONTOLOGY_DIR = Path(__file__).resolve().parents[3] / "ontology"
BASE_SCHEMA = ONTOLOGY_DIR / "base.yaml"
METAMODEL_SCHEMA = ONTOLOGY_DIR / "metamodel.yaml"
BASE_IMPORT = "pxos_base"
KIND_ANNOTATION = "pxos.kind"
BASE_VERSION_ANNOTATION = "pxos.base_version"


class InvalidPackage(PxosError):
    """The package breaks a layer, version or metamodel rule."""


class Kind(StrEnum):
    CANONICAL = "canonical"
    CONTEXT = "context"


@dataclass(frozen=True)
class ActionType:
    name: str
    creates: str
    approver: str
    reversible: bool
    rule_parameters: tuple[str, ...]


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    base_version: str
    schema: SchemaView
    kinds: dict[str, Kind]
    actions: tuple[ActionType, ...]


def load_package(schema_path: Path, actions_path: Path) -> Package:
    base = SchemaView(str(BASE_SCHEMA))
    view = SchemaView(str(schema_path), importmap={BASE_IMPORT: str(BASE_SCHEMA.with_suffix(""))})
    schema = view.schema
    name = str(schema.name)

    if BASE_IMPORT not in (schema.imports or []):
        raise InvalidPackage(f"{name}: package must import {BASE_IMPORT}")
    if not schema.version:
        raise InvalidPackage(f"{name}: package must declare a version")
    base_version = _annotation(schema.annotations, BASE_VERSION_ANNOTATION)
    if base_version is None:
        raise InvalidPackage(f"{name}: package must declare {BASE_VERSION_ANNOTATION}")
    if not is_compatible(base_version, str(base.schema.version)):
        raise InvalidPackage(
            f"{name}: built for base {base_version}, kernel has {base.schema.version}"
        )

    base_classes = set(base.all_classes())
    own_classes = set(view.all_classes(imports=False))
    redefined = sorted(own_classes & base_classes)
    if redefined:
        raise InvalidPackage(f"{name}: package redefines base types {redefined}")

    kinds = {class_name: class_kind(view, class_name, name) for class_name in sorted(own_classes)}
    actions = _load_actions(view, kinds, actions_path, name)
    return Package(
        name=name,
        version=str(schema.version),
        base_version=base_version,
        schema=view,
        kinds=kinds,
        actions=actions,
    )


def class_kind(view: SchemaView, class_name: str, package: str) -> Kind:
    value = _annotation(view.get_class(class_name).annotations, KIND_ANNOTATION)
    try:
        return Kind(value or "")
    except ValueError:
        raise InvalidPackage(
            f"{package}: {class_name} must declare {KIND_ANNOTATION} as canonical or context"
        ) from None


def is_compatible(declared: str, available: str) -> bool:
    """Same major version; below 1.0 the minor version must match too."""
    declared_major, declared_minor, *_ = declared.split(".")
    available_major, available_minor, *_ = available.split(".")
    if declared_major != available_major:
        return False
    return declared_major != "0" or declared_minor == available_minor


def _load_actions(
    view: SchemaView, kinds: dict[str, Kind], actions_path: Path, package: str
) -> tuple[ActionType, ...]:
    raw = yaml.safe_load(actions_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise InvalidPackage(f"{package}: actions file must be a list of action types")

    actions = []
    for item in raw:
        report = validate(item, str(METAMODEL_SCHEMA), "ActionType", strict=True)
        if report.results:
            messages = "; ".join(result.message for result in report.results)
            raise InvalidPackage(f"{package}: invalid action type {item!r}: {messages}")
        action = ActionType(
            name=item["name"],
            creates=item["creates"],
            approver=item["approver"],
            reversible=item["reversible"],
            rule_parameters=tuple(item.get("rule_parameters", [])),
        )
        if kinds.get(action.creates) is not Kind.CANONICAL:
            raise InvalidPackage(
                f"{package}: {action.name} must create a canonical type of the package"
            )
        attributes = set(view.class_slots(action.creates))
        unknown = sorted(set(action.rule_parameters) - attributes)
        if unknown:
            raise InvalidPackage(f"{package}: {action.name} rule parameters {unknown} unknown")
        actions.append(action)

    names = [action.name for action in actions]
    if len(names) != len(set(names)):
        raise InvalidPackage(f"{package}: duplicated action type names")
    return tuple(actions)


def _annotation(annotations: Any, key: str) -> str | None:
    if not annotations or key not in annotations:
        return None
    return str(annotations[key].value)
