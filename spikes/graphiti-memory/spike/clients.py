"""Clientes nativos Graphiti/Gemini; medição apenas das invocações ao SDK."""

import asyncio
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from google import genai
from google.auth.credentials import Credentials
from google.genai import types
from graphiti_core import Graphiti
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.gemini_client import GeminiClient

from spike.config import NEO4J_URI, neo4j_password


class GcloudCredentials(Credentials):
    """Token curto por impersonação; não lê ADC nem altera a configuração ativa."""

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def refresh(self, request):
        s = self.settings
        result = subprocess.run(
            [
                "gcloud",
                "auth",
                "print-access-token",
                f"--account={s.account}",
                f"--project={s.project}",
                f"--impersonate-service-account={s.service_account}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Falha na impersonação do spike-runner; verifique login e IAM")
        self.token = result.stdout.strip()
        self.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=50)


class MeasuredModels:
    def __init__(self, models, path, location):
        self.models, self.path, self.location = models, path, location

    async def call(self, method, **kwargs):
        started = time.perf_counter()
        row = {"method": method, "model": kwargs["model"], "location": self.location}
        try:
            result = await getattr(self.models, method)(**kwargs)
            usage = getattr(result, "usage_metadata", None)
            row["usage"] = usage.model_dump(mode="json") if usage else None
            row["status"] = "ok"
            return result
        except Exception as exc:
            row.update(status="error", error_type=type(exc).__name__)
            raise
        finally:
            row["seconds"] = time.perf_counter() - started
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(row) + "\n")

    async def generate_content(self, **kwargs):
        return await self.call("generate_content", **kwargs)

    async def embed_content(self, **kwargs):
        return await self.call("embed_content", **kwargs)


async def connect(settings, metrics_path):
    credentials = GcloudCredentials(settings)
    await asyncio.to_thread(credentials.refresh, None)
    clients = []
    measured = []
    for location in (settings.location, settings.embedding_location):
        client = genai.Client(
            vertexai=True,
            project=settings.project,
            location=location,
            credentials=credentials,
            http_options=types.HttpOptions(timeout=120_000),
        )
        clients.append(client)
        measured.append(
            SimpleNamespace(
                aio=SimpleNamespace(
                    models=MeasuredModels(client.aio.models, metrics_path, location)
                )
            )
        )
    config = LLMConfig(model=settings.model, small_model=settings.model, temperature=0)
    graph = Graphiti(
        NEO4J_URI,
        "neo4j",
        neo4j_password(),
        llm_client=GeminiClient(config=config, client=measured[0]),
        embedder=GeminiEmbedder(
            GeminiEmbedderConfig(
                embedding_model=settings.embedding_model, embedding_dim=settings.embedding_dim
            ),
            client=measured[1],
        ),
        cross_encoder=GeminiRerankerClient(config=config, client=measured[0]),
        store_raw_episode_content=True,
        max_coroutines=2,
    )
    return graph, clients


async def close(graph, clients):
    await graph.close()
    for client in clients:
        await client.aio.aclose()
        client.close()
