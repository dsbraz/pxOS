#!/bin/bash
set -eu
# Credenciais públicas exclusivamente de fixture, diferentes por instalação e ator.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v installation="$INSTALLATION" -f /docker-entrypoint-initdb.d/schema.txt
