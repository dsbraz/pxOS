import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEO4J_URI = "bolt://127.0.0.1:17687"


@dataclass(frozen=True)
class Settings:
    project: str
    account: str
    model: str
    location: str
    embedding_model: str
    embedding_location: str
    embedding_dim: int

    @classmethod
    def load(cls):
        project = os.environ.get("SPIKE_GCP_PROJECT", "")
        account = os.environ.get("SPIKE_GCP_ACCOUNT", "")
        if not re.fullmatch(r"pxos-spikes(?:-[a-z0-9-]+)?", project):
            raise ValueError("SPIKE_GCP_PROJECT deve ser o projeto exclusivo pxos-spikes[-sufixo]")
        if not account:
            raise ValueError("Defina SPIKE_GCP_ACCOUNT explicitamente")
        dim = int(os.environ.get("SPIKE_EMBEDDING_DIM", "768"))
        if not 1 <= dim <= 3072:
            raise ValueError("SPIKE_EMBEDDING_DIM deve estar entre 1 e 3072")
        return cls(
            project,
            account,
            os.getenv("SPIKE_LLM_MODEL", "gemini-3.8-flash"),
            os.getenv("SPIKE_LLM_LOCATION", "global"),
            os.getenv("SPIKE_EMBEDDING_MODEL", "gemini-embedding-001"),
            os.getenv("SPIKE_EMBEDDING_LOCATION", "us-central1"),
            dim,
        )

    @property
    def service_account(self):
        return f"spike-runner@{self.project}.iam.gserviceaccount.com"


def neo4j_password():
    return os.getenv("SPIKE_NEO4J_PASSWORD", "pxos-spike-local")
