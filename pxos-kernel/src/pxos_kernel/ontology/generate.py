"""Generate Pydantic models and JSON Schema for ontology packages (ADR 0003 §6).

A package directory holds ``ontology.yaml``; the native LinkML generators write
``generated.py`` and ``generated.schema.json`` next to it. The base is always included.

    uv run python -m pxos_kernel.ontology.generate [--check] [PACKAGE_DIR ...]
"""

import argparse
import sys
from pathlib import Path

from linkml.generators.jsonschemagen import JsonSchemaGenerator
from linkml.generators.pydanticgen import PydanticGenerator

from pxos_kernel.ontology.loader import BASE_DIR, BASE_IMPORT, BASE_SCHEMA

MODELS_FILE = "generated.py"
JSON_SCHEMA_FILE = "generated.schema.json"


def render(package_dir: Path) -> dict[Path, str]:
    """Return the generated files of one package, keyed by path."""
    schema = str(package_dir / "ontology.yaml")
    importmap = {BASE_IMPORT: str(BASE_SCHEMA.with_suffix(""))}
    models = PydanticGenerator(schema, importmap=importmap, metadata_mode=None).serialize()
    json_schema = JsonSchemaGenerator(schema, importmap=importmap).serialize()
    return {
        package_dir / MODELS_FILE: models,
        package_dir / JSON_SCHEMA_FILE: json_schema.rstrip("\n") + "\n",
    }


def stale_files(package_dirs: list[Path]) -> list[Path]:
    """Generated files that differ from what the LinkML would produce now."""
    return [
        path
        for package_dir in [BASE_DIR, *package_dirs]
        for path, content in render(package_dir).items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]


def write(package_dirs: list[Path]) -> None:
    for package_dir in [BASE_DIR, *package_dirs]:
        for path, content in render(package_dir).items():
            path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if any file is stale")
    parser.add_argument("package_dirs", nargs="*", type=Path)
    args = parser.parse_args(argv)
    if args.check:
        stale = stale_files(args.package_dirs)
        for path in stale:
            print(f"stale: {path}", file=sys.stderr)
        return 1 if stale else 0
    write(args.package_dirs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
