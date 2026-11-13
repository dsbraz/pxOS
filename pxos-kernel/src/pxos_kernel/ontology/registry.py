"""Registration of packages by the composition root (ADR 0003 §1).

The distribution imports its own generated models and hands them to the kernel with
the package directory. The kernel never imports distribution code, not even by name.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import BaseModel, ValidationError

from pxos_kernel.ontology.loader import InvalidPackage, Kind, Package, load_package


class InvalidPayload(InvalidPackage):
    """A payload does not validate against the package's generated model."""


@dataclass(frozen=True)
class RegisteredPackage:
    package: Package
    models: dict[str, type[BaseModel]]

    def validate(self, type_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        model = self.models.get(type_name)
        if model is None:
            raise InvalidPayload(f"{self.package.name}: {type_name} is not a canonical type")
        try:
            return model.model_validate(payload).model_dump(mode="json", exclude_none=True)
        except ValidationError as error:
            raise InvalidPayload(f"{self.package.name}: invalid {type_name}: {error}") from None


class Registry:
    def __init__(self) -> None:
        self._packages: dict[str, RegisteredPackage] = {}

    def register(self, package_dir: Path, models: ModuleType) -> RegisteredPackage:
        package = load_package(package_dir)
        if package.name in self._packages:
            raise InvalidPackage(f"{package.name}: package already registered")
        resolved = {}
        for type_name, kind in package.kinds.items():
            if kind is not Kind.CANONICAL:
                continue
            model = getattr(models, type_name, None)
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                raise InvalidPackage(f"{package.name}: generated model {type_name} not found")
            resolved[type_name] = model
        registered = RegisteredPackage(package=package, models=resolved)
        self._packages[package.name] = registered
        return registered

    def get(self, name: str) -> RegisteredPackage:
        try:
            return self._packages[name]
        except KeyError:
            raise InvalidPackage(f"{name}: package not registered") from None

    def __iter__(self) -> Iterator[RegisteredPackage]:
        return iter(self._packages.values())
