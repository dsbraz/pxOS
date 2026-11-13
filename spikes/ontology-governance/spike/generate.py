"""Geração nativa LinkML, como nos demais spikes."""

from pathlib import Path

from linkml.generators.pydanticgen import PydanticGenerator

ROOT = Path(__file__).resolve().parent.parent


def generate(package):
    return PydanticGenerator(
        str(ROOT / "packages" / package / "ontology.yaml"), metadata_mode=None
    ).serialize()


if __name__ == "__main__":
    for path in sorted((ROOT / "packages").iterdir()):
        (ROOT / "spike" / f"generated_{path.name}.py").write_text(generate(path.name))
