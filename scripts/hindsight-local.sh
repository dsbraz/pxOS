#!/usr/bin/env bash
# Hindsight local para a execução real e opt-in da fatia 2 (PXOS-53, PXOS-56).
# Banco: o Postgres do Compose (pgvector). Modelo e embeddings: Vertex no projeto do
# desenvolvedor. As credenciais vêm de GOOGLE_APPLICATION_CREDENTIALS; nada é gravado aqui.
# Uso: GOOGLE_APPLICATION_CREDENTIALS=... PXOS_VERTEX_PROJECT=... scripts/hindsight-local.sh
set -euo pipefail

: "${GOOGLE_APPLICATION_CREDENTIALS:?defina GOOGLE_APPLICATION_CREDENTIALS}"
: "${PXOS_VERTEX_PROJECT:?defina PXOS_VERTEX_PROJECT}"
port="${PXOS_HINDSIGHT_PORT:-18888}"
db_port="${PXOS_DB_PORT:-25432}"

docker compose exec -T postgres psql -U pxos -d postgres -tc \
  "SELECT 1 FROM pg_database WHERE datname = 'hindsight_local'" | grep -q 1 ||
  docker compose exec -T postgres psql -U pxos -d postgres -c "CREATE DATABASE hindsight_local"
docker compose exec -T postgres psql -U pxos -d hindsight_local -qc \
  "CREATE EXTENSION IF NOT EXISTS vector"

export GOOGLE_CLOUD_PROJECT="$PXOS_VERTEX_PROJECT"
export HINDSIGHT_API_DATABASE_URL="postgresql://pxos:pxos-local@127.0.0.1:${db_port}/hindsight_local"
export HINDSIGHT_API_LLM_PROVIDER=vertexai
export HINDSIGHT_API_LLM_VERTEXAI_PROJECT_ID="$PXOS_VERTEX_PROJECT"
export HINDSIGHT_API_LLM_VERTEXAI_REGION="${PXOS_VERTEX_LLM_REGION:-global}"
export HINDSIGHT_API_LLM_MODEL="${PXOS_VERTEX_LLM_MODEL:-gemini-3.8-flash}"
export HINDSIGHT_API_LLM_PROMPT_CACHE_ENABLED=false
export HINDSIGHT_API_EMBEDDINGS_PROVIDER=google
export HINDSIGHT_API_EMBEDDINGS_VERTEXAI_PROJECT_ID="$PXOS_VERTEX_PROJECT"
export HINDSIGHT_API_EMBEDDINGS_VERTEXAI_REGION="${PXOS_VERTEX_EMBEDDING_REGION:-us-central1}"
export HINDSIGHT_API_EMBEDDINGS_GEMINI_MODEL=gemini-embedding-001
export HINDSIGHT_API_EMBEDDINGS_GEMINI_OUTPUT_DIMENSIONALITY=768
export HINDSIGHT_API_RERANKER_PROVIDER=rrf
export HINDSIGHT_API_VECTOR_EXTENSION=pgvector
export HINDSIGHT_API_TEXT_SEARCH_EXTENSION=native
export HINDSIGHT_API_TEXT_SEARCH_EXTENSION_NATIVE_LANGUAGE=portuguese
export HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION=false
# Traces de modelo guardam conteúdo restrito; ficam desligados (ADR 0001).
export HINDSIGHT_API_LLM_TRACE_ENABLED=false
export HINDSIGHT_API_OTEL_TRACES_ENABLED=false
export HINDSIGHT_API_MCP_ENABLED=false

exec uvx --python 3.12 --from hindsight-api-slim==1.2.1 \
  uvicorn hindsight_api.server:app --host 127.0.0.1 --port "$port"
