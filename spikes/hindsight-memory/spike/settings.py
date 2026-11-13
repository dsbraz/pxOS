import json
import os
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
API_URL = "http://127.0.0.1:18888"
DB_PORT = 15432


def keys():
    return json.loads((ROOT / ".secrets/api.json").read_text())


def configure():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    if os.getenv("SPIKE_GCP_PROJECT", "pxos-spikes") != "pxos-spikes":
        raise ValueError("Este spike só pode usar pxos-spikes")
    cloud = json.loads((ROOT / "cloud.json").read_text())
    if cloud["project"] != "pxos-spikes" or cloud["cluster"] != "hindsight-spike":
        raise ValueError("Recurso cloud não pertence a este spike")
    adc = ROOT / ".secrets/adc.json"
    credential_config = json.loads(adc.read_text())
    if (
        credential_config.get("type") != "impersonated_service_account"
        or credential_config.get("quota_project_id") != "pxos-spikes"
        or not credential_config.get("service_account_impersonation_url", "").endswith(
            "/spike-runner@pxos-spikes.iam.gserviceaccount.com:generateAccessToken"
        )
    ):
        raise ValueError("ADC deve impersonar spike-runner exclusivamente em pxos-spikes")
    password = json.loads((ROOT / ".secrets/database.json").read_text())["password"]
    dsn = f"postgresql://postgres:{quote(password, safe='')}@127.0.0.1:{DB_PORT}/hindsight_spike"
    settings = {
        "GOOGLE_APPLICATION_CREDENTIALS": str(adc),
        "GOOGLE_CLOUD_PROJECT": "pxos-spikes",
        "HINDSIGHT_API_DATABASE_URL": dsn,
        "HINDSIGHT_API_DATABASE_SCHEMA": "public",
        "HINDSIGHT_API_LLM_PROVIDER": "vertexai",
        "HINDSIGHT_API_LLM_VERTEXAI_PROJECT_ID": "pxos-spikes",
        "HINDSIGHT_API_LLM_VERTEXAI_REGION": os.getenv("SPIKE_LLM_LOCATION", "global"),
        "HINDSIGHT_API_LLM_MODEL": os.getenv("SPIKE_LLM_MODEL", "gemini-3.8-flash"),
        "HINDSIGHT_API_LLM_MAX_CONCURRENT": "2",
        "HINDSIGHT_API_LLM_PROMPT_CACHE_ENABLED": "false",
        "HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS": "32768",
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "google",
        "HINDSIGHT_API_EMBEDDINGS_VERTEXAI_PROJECT_ID": "pxos-spikes",
        "HINDSIGHT_API_EMBEDDINGS_VERTEXAI_REGION": os.getenv(
            "SPIKE_EMBEDDING_LOCATION", "us-central1"
        ),
        "HINDSIGHT_API_EMBEDDINGS_GEMINI_MODEL": os.getenv(
            "SPIKE_EMBEDDING_MODEL", "gemini-embedding-001"
        ),
        "HINDSIGHT_API_EMBEDDINGS_GEMINI_OUTPUT_DIMENSIONALITY": os.getenv(
            "SPIKE_EMBEDDING_DIM", "768"
        ),
        "HINDSIGHT_API_EMBEDDINGS_GEMINI_BATCH_SIZE": "1",
        "HINDSIGHT_API_RERANKER_PROVIDER": "rrf",
        "HINDSIGHT_API_VECTOR_EXTENSION": "pgvector",
        "HINDSIGHT_API_TEXT_SEARCH_EXTENSION": "native",
        "HINDSIGHT_API_TEXT_SEARCH_EXTENSION_NATIVE_LANGUAGE": "portuguese",
        "HINDSIGHT_API_TENANT_EXTENSION": "spike.hooks:SpikeTenant",
        "HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION": "spike.hooks:SpikePolicy",
        "HINDSIGHT_API_WORKER_ID": "pxos-hindsight-spike",
        "HINDSIGHT_API_WORKER_MAX_SLOTS": "2",
        "HINDSIGHT_API_WORKER_CONSOLIDATION_RESERVED_SLOTS": "0",
        "HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION": "true",
        "HINDSIGHT_API_METRICS_INCLUDE_BANK_ID": "true",
        "HINDSIGHT_API_OTEL_TRACES_ENABLED": "false",
        "HINDSIGHT_API_LLM_TRACE_ENABLED": os.getenv("SPIKE_LLM_TRACE_ENABLED", "false"),
        "HINDSIGHT_API_LLM_TRACE_DELETE_WITH_DOCUMENT": os.getenv(
            "SPIKE_DELETE_TRACES_WITH_DOCUMENT", "true"
        ),
        "HINDSIGHT_API_MCP_ENABLED": "false",
    }
    # O ambiente do experimento é explícito; não herdar configurações Hindsight de outro app.
    for name in list(os.environ):
        if name.startswith("HINDSIGHT_API_"):
            del os.environ[name]
    os.environ.update(settings)
    return dsn
