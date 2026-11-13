# pxOS

Monorepo do kernel pxOS e suas distribuições, incluindo BRQ@work.
O kernel está em construção (fatia 1); spikes são experimentos isolados.

## Conteúdo

- [PRD](pxos-brq-work-prd.html)
- [Roadmap](ROADMAP.md) e [backlog](BACKLOG-KERNEL.md)
- [Decisões de arquitetura](docs/adr/)
- [Ontologia e governança](spikes/ontology-governance/README.md)
- [Graphiti](spikes/graphiti-memory/README.md) e [Hindsight](spikes/hindsight-memory/README.md)

## Desenvolvimento

O código de produto fica em `pxos-kernel/` (kernel) e `brq-at-work/` (distribuição),
num workspace uv com Python 3.12. A fronteira entre os dois está nos ADRs 0002 e 0003.

```sh
uv sync
docker compose up -d --wait   # Postgres 16 + pgvector em 127.0.0.1:25432
uv run ruff check pxos-kernel brq-at-work
uv run ruff format --check pxos-kernel brq-at-work
uv run mypy
uv run lint-imports          # o kernel não importa a distribuição
uv run pytest                # neutralidade e integração; exige o Postgres do Compose
```

Modelos Pydantic e JSON Schema são gerados do LinkML de cada pacote (`generated.py` e
`generated.schema.json`, ao lado do `ontology.yaml`). Depois de mudar uma ontologia:

```sh
uv run python -m pxos_kernel.ontology.generate \
  pxos-kernel/tests/retail_fixture brq-at-work/src/brq_at_work/ontology/work_context
```

O teste de snapshot e o CI (`--check`) falham se o gerado divergir do LinkML.

Para ver o ciclo canônico funcionando (proposta, recusas, aprovação, correção e leitura
em duas datas) num banco local `pxos_demo`:

```sh
PYTHONPATH=. uv run python brq-at-work/examples/slice1_demo.py
```

No CI, a memória de contexto é o adaptador falso. A execução real é opt-in e local, com o
Hindsight sobre o Postgres do Compose e o modelo no Vertex (gasta tokens no projeto
indicado):

```sh
GOOGLE_APPLICATION_CREDENTIALS=... PXOS_VERTEX_PROJECT=... scripts/hindsight-local.sh
PXOS_HINDSIGHT_URL=http://127.0.0.1:18888 uv run pytest -k hindsight
```

O CI de produto (`.github/workflows/ci.yml`) roda os mesmos checks. Os experimentos em
`spikes/` ficam fora do workspace e do CI; seus procedimentos estão nas respectivas pastas.

Veja [contribuição](CONTRIBUTING.md), [segurança](SECURITY.md) e [Apache-2.0](LICENSE).
