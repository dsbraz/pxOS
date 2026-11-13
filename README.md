# pxOS

Monorepo do kernel pxOS e suas distribuições, incluindo BRQ@work.
O produto está em planejamento; spikes são experimentos isolados.

## Conteúdo

- [PRD](pxos-brq-work-prd.html)
- [Roadmap](ROADMAP.md) e [backlog](BACKLOG-KERNEL.md)
- [Graphiti](spikes/graphiti-memory/README.md) e [Hindsight](spikes/hindsight-memory/README.md)

## Desenvolvimento

Python 3.12 e uv 0.13.7. Cada componente mantém seu próprio lockfile.
Na pasta do componente:

```sh
uv sync --locked
uv run --frozen ruff check spike tests
uv run --frozen ruff format --check spike tests
uv run --frozen pytest -q
```

O CI raiz executa lint, formatação e testes dos componentes existentes,
incluindo integração Neo4j via Compose. Não usa GCP ou inferência paga.
Novos componentes devem acrescentar seus checks quando implementados.

Veja [contribuição](CONTRIBUTING.md), [segurança](SECURITY.md) e [Apache-2.0](LICENSE).
