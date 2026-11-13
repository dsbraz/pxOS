# pxOS

Monorepo do kernel pxOS e suas distribuições, incluindo BRQ@work.
O produto está em planejamento; spikes são experimentos isolados.

## Conteúdo

- [PRD](pxos-brq-work-prd.html)
- [Roadmap](ROADMAP.md) e [backlog](BACKLOG-KERNEL.md)
- [Decisões de arquitetura](docs/adr/)
- [Ontologia e governança](spikes/ontology-governance/README.md)
- [Graphiti](spikes/graphiti-memory/README.md) e [Hindsight](spikes/hindsight-memory/README.md)

## Desenvolvimento

Ainda não há código de produto nem pipeline de CI de produto.
Os experimentos ficam isolados em `spikes/`; seus requisitos, dependências
e procedimentos de validação estão documentados nas respectivas pastas.
O CI será definido conforme os componentes de produto forem implementados.

Veja [contribuição](CONTRIBUTING.md), [segurança](SECURITY.md) e [Apache-2.0](LICENSE).
