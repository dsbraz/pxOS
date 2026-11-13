# ADR 0001 — Memória de contexto e estado canônico

**Status:** aceito em 13/11/2026. Fecha o PXOS-3.

## Contexto

O PRD (§16) deixou em aberto construir ou adotar a camada de memória. Quatro spikes
isolados em `spikes/` responderam à pergunta. Os ADRs de spike não são decisões de
produto; este ADR consolida o que deles vira produto.

## Decisão

O kernel tem **duas camadas de memória**, com responsabilidades separadas.

| Camada | O que guarda | Implementação | Quem escreve |
|---|---|---|---|
| **Contexto** | Conteúdo ingerido, fatos extraídos, entidades de índice, recuperação e respostas | Hindsight sobre AlloyDB, com extração nativa e extensões públicas | Ingestão, sem aprovação humana |
| **Estado canônico** | Fatos tipados que **autorizam ação ou alimentam medição** (ex.: compromisso, papel, contrato) | Código próprio do pxOS em PostgreSQL/AlloyDB | Só pelo ciclo proposta → aprovação |

Fronteira: um fato só é canônico se uma ação, uma política ou uma métrica depende dele.
O resto é contexto. O tipo declara isso no pacote de ontologia.

O contexto **não aprova** fatos. Uma proposta canônica cita o contexto como evidência
(`source`, `quote`, `context_ref`). Propostas não voltam para o contexto, para que um
rascunho nunca pareça fato confirmado.

### Rejeitado

- **Graphiti + Neo4j como memória canônica.** Juntou identidades distintas, manteve fatos
  conflitantes como atuais, vazou conhecimento posterior em consultas históricas, não
  aplica permissão da fonte e não permite aprovar antes de gravar
  (`spikes/graphiti-memory/reports/ADR-001.md`). Neo4j não é tecnologia aprovada.
- **Mem0 e LangExtract.** Sem lacuna demonstrada que os justifique.
- **Segundo extrator, resolvedor ou reconciliador ao lado do Hindsight.** O pxOS não
  reconstrói o que o Hindsight já faz para contexto.

## Critérios do PXOS-3, por camada

| Critério | Contexto (Hindsight) | Estado canônico (próprio) |
|---|---|---|
| Duas datas por fato | Interpretação temporal correta nas respostas; sem contrato `valid_at` + `known_at` | Validado em spike: `valid_from` + instante de registro, consulta "válido em / sabido em" |
| Invalidação sem apagar | Consolidação nativa | Versões só acrescentadas; **intervalos finitos e invalidação ainda a construir (PXOS-7)** |
| Isolamento | **Tabelas sem RLS**; escopo por tags no servidor. Isolamento entre clientes vem da instalação dedicada | RLS validado em spike para permissões internas |
| Expurgo real | Limpo só com `HINDSIGHT_API_LLM_TRACE_ENABLED=false`; com traces ligados sobram resíduos | **A construir (PXOS-10)** |
| Portabilidade | PostgreSQL + pgvector; Hindsight é open source | PostgreSQL puro |

## Consequências

- O PXOS-7 constrói o estado canônico sobre o contrato do spike de governança.
- O PXOS-16 deixa de ser um índice pgvector próprio e vira busca autorizada sobre o Hindsight.
- PXOS-25 a 28 deixam de reconstruir a extração: tratam da proposta canônica, da evidência
  literal, das chaves de identidade e da revisão.
- O PXOS-10 cobre as duas camadas; os traces de modelo do Hindsight ficam desligados.
- Ainda não validado: o ciclo canônico rodando no AlloyDB real, evidência literal, meta de
  99% de junção, residência de inferência. São critérios de aceite das issues, não novos spikes.
