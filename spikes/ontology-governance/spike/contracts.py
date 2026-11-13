import hashlib
import importlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Package:
    def __init__(self, name):
        # Apenas pacotes locais versionados; não carregar nomes/código externos.
        paths = {p.name: p for p in (ROOT / "packages").iterdir() if p.is_dir()}
        path = paths[name]
        self.name = name
        self.manifest = yaml.safe_load((path / "manifest.yaml").read_text())
        self.fingerprint = digest(
            {
                "manifest": self.manifest,
                "ontology": (path / "ontology.yaml").read_text(),
            }
        )
        self.model = getattr(
            importlib.import_module(f"spike.generated_{name}"), self.manifest["type"]
        )

    def validate(self, payload):
        return self.model.model_validate(payload).model_dump(mode="json")
