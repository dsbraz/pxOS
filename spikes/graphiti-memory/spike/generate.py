"""Geração nativa LinkML; modelos gerados nunca são editados manualmente."""

from pathlib import Path

from linkml.generators.pydanticgen import PydanticGenerator

ROOT = Path(__file__).resolve().parent.parent


def generate() -> str:
    return PydanticGenerator(str(ROOT / "ontology/memory.yaml"), metadata_mode=None).serialize()


if __name__ == "__main__":
    (ROOT / "spike/generated.py").write_text(generate(), encoding="utf-8")
