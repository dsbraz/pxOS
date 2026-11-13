"""Load a domain package on top of the base ontology and check its rules.

A package directory holds ``ontology.yaml`` (LinkML, importing ``pxos_base``) and
``manifest.yaml`` (validated against the metamodel). The kernel only knows what the
package declares.
"""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from linkml.validator import validate
from linkml_runtime.utils.schemaview import SchemaView

from pxos_kernel.errors import PxosError

ONTOLOGY_DIR = Path(__file__).resolve().parent
BASE_DIR = ONTOLOGY_DIR / "base"
BASE_SCHEMA = BASE_DIR / "ontology.yaml"
METAMODEL_SCHEMA = ONTOLOGY_DIR / "metamodel.yaml"
BASE_IMPORT = "pxos_base"
KIND_ANNOTATION = "pxos.kind"
BASE_VERSION_ANNOTATION = "pxos.base_version"


class InvalidPackage(PxosError):
    """The package breaks a layer, version, manifest or metamodel rule."""


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
    digest: str
    schema: SchemaView
    kinds: dict[str, Kind]
    readers: dict[str, tuple[str, ...]]
    actions: tuple[ActionType, ...]

    def action(self, name: str) -> ActionType:
        for action in self.actions:
            if action.name == name:
                return action
        raise InvalidPackage(f"{self.name}: unknown action {name}")


def load_package(package_dir: Path) -> Package:
    schema_path = package_dir / "ontology.yaml"
    manifest_path = package_dir / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    base = SchemaView(str(BASE_SCHEMA))
    view = SchemaView(str(schema_path), importmap={BASE_IMPORT: str(BASE_SCHEMA.with_suffix(""))})
    schema = view.schema
    name = str(schema.name)

    report = validate(manifest, str(METAMODEL_SCHEMA), "PackageManifest", strict=True)
    if report.results:
        messages = "; ".join(result.message for result in report.results)
        raise InvalidPackage(f"{name}: invalid manifest: {messages}")
    if manifest["name"] != name or manifest["version"] != schema.version:
        raise InvalidPackage(f"{name}: manifest name and version must match the LinkML schema")

    if BASE_IMPORT not in (schema.imports or []):
        raise InvalidPackage(f"{name}: package must import {BASE_IMPORT}")
    base_version = _annotation(schema.annotations, BASE_VERSION_ANNOTATION)
    if base_version is None:
        raise InvalidPackage(f"{name}: package must declare {BASE_VERSION_ANNOTATION}")
    if not is_compatible(base_version, str(base.schema.version)):
        raise InvalidPackage(
            f"{name}: built for base {base_version}, kernel has {base.schema.version}"
        )

    own_classes = set(view.all_classes(imports=False))
    redefined = sorted(own_classes & set(base.all_classes()))
    if redefined:
        raise InvalidPackage(f"{name}: package redefines base types {redefined}")

    kinds = {class_name: class_kind(view, class_name, name) for class_name in sorted(own_classes)}
    readers = _readers(manifest, kinds, name)
    actions = _actions(manifest, view, kinds, readers, name)
    return Package(
        name=name,
        version=str(schema.version),
        base_version=base_version,
        digest=_digest(manifest, schema_path),
        schema=view,
        kinds=kinds,
        readers=readers,
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
    try:
        declared_major, declared_minor, _ = (int(part) for part in declared.split("."))
        available_major, available_minor, _ = (int(part) for part in available.split("."))
    except ValueError:
        raise InvalidPackage(
            f"versions must be MAJOR.MINOR.PATCH: {declared}, {available}"
        ) from None
    if declared_major != available_major:
        return False
    return declared_major != 0 or declared_minor == available_minor


def _readers(
    manifest: dict[str, Any], kinds: dict[str, Kind], package: str
) -> dict[str, tuple[str, ...]]:
    declared = {item["name"]: tuple(item.get("readers", [])) for item in manifest["types"]}
    if set(declared) != set(kinds):
        raise InvalidPackage(f"{package}: manifest types must be exactly the package types")
    for type_name, roles in declared.items():
        if kinds[type_name] is Kind.CANONICAL and not roles:
            raise InvalidPackage(f"{package}: canonical type {type_name} must declare readers")
        if kinds[type_name] is Kind.CONTEXT and roles:
            raise InvalidPackage(f"{package}: context type {type_name} cannot declare readers")
    return {type_name: roles for type_name, roles in declared.items() if roles}


def _actions(
    manifest: dict[str, Any],
    view: SchemaView,
    kinds: dict[str, Kind],
    readers: dict[str, tuple[str, ...]],
    package: str,
) -> tuple[ActionType, ...]:
    actions = []
    for item in manifest.get("actions", []):
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
        if action.approver not in readers[action.creates]:
            raise InvalidPackage(f"{package}: approver of {action.name} must read {action.creates}")
        unknown = sorted(set(action.rule_parameters) - set(view.class_slots(action.creates)))
        if unknown:
            raise InvalidPackage(f"{package}: {action.name} rule parameters {unknown} unknown")
        actions.append(action)

    names = [action.name for action in actions]
    if len(names) != len(set(names)):
        raise InvalidPackage(f"{package}: duplicated action type names")
    return tuple(actions)


def _digest(manifest: dict[str, Any], schema_path: Path) -> str:
    """Identity of what was reviewed: manifest, package and base LinkML (parsed, so
    comments and formatting do not count)."""
    content = {
        "manifest": manifest,
        "ontology": yaml.safe_load(schema_path.read_text(encoding="utf-8")),
        "base": yaml.safe_load(BASE_SCHEMA.read_text(encoding="utf-8")),
    }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _annotation(annotations: Any, key: str) -> str | None:
    if not annotations or key not in annotations:
        return None
    return str(annotations[key].value)
