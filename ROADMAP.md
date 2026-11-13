# Roadmap: pxOS kernel → BRQ@work

## Contexto

O PRD `pxos-brq-work-prd.html` (v0.24) descreve uma plataforma que ainda não existe: o **kernel do pxOS** (Parte A) e sua primeira distribuição, a **BRQ@work** (Parte B). Os spikes de memória, ontologia e governança, e execução e isolamento foram concluídos em 13/11/2026 (`spikes/`). O código de produto começa agora.

Decisões já tomadas:
- **Entregável:** roadmap em fases, com marcos, dependências, gates e critérios de saída.
- **Primeiro marco:** **kernel completo**, ou seja, os 13 contêineres do §5 e os 13 requisitos do §4. A construção começa por uma **fatia vertical** (ver Fase 0–2) que já roda o pacote de contexto de trabalho da BRQ@work.
- **Memória:** contexto no Hindsight sobre AlloyDB; estado canônico tipado e governado próprio em PostgreSQL ([ADR 0001](docs/adr/0001-memoria-contexto-e-estado-canonico.md)). Graphiti, Neo4j, Mem0 e LangExtract rejeitados.
- **Fronteira kernel/distribuição** por natureza, com o mantenedor como árbitro ([ADR 0002](docs/adr/0002-fronteira-kernel-distribuicao.md)).
- **Arquitetura e padrões de código** em [ADR 0003](docs/adr/0003-arquitetura-e-padroes-de-codigo.md).
- **Implantação:** instalação dedicada por cliente é o padrão, e dentro dela valem as permissões internas. O modo compartilhado fica adiado.
- **Time:** você e eu. O gargalo é o seu tempo de revisão e os acessos externos (TI, jurídico, GCP), não a escrita de código. Por isso o plano é sequenciado por critério de saída, sem datas.

**Risco aceito:** o próprio PRD aponta o risco "kernel com a forma da BRQ@work". Construir o kernel primeiro inverte esse risco: o kernel fica sem validação de uso diário. A mitigação é um **conjunto de fixtures de referência** que exercita o kernel como duas distribuições diferentes fariam:
- 2 instalações, com permissão restrita entre pessoas dentro de uma;
- 1 conector falso de conteúdo e 1 de registros operacionais;
- 1 canal falso;
- 1 pacote de ontologia de outro domínio (neutralidade), além do pacote real de contexto de trabalho da BRQ@work.

Assim cada fase tem um critério executável.

## Princípios de execução

- **Local primeiro** (CLAUDE.md): Docker Compose com portas só em loopback, Postgres 16 + pgvector local e emuladores (Pub/Sub, Firestore/Datastore se preciso). Cada serviço GCP (Vertex, Agent Gateway, Agent Engine, BigQuery, Secret Manager, Workflows) fica atrás de um **adaptador** com uma implementação local e uma GCP. Isso também atende o requisito 12 (portabilidade).
- **Monorepo:** workspace uv na raiz com `pxos-kernel/` (kernel) e `brq-at-work/` (distribuição), `docs/adr/` e `spikes/`. Outras pastas (`infra/`, `evals/`, Constituição) nascem com a issue que as usa.
- **Stack:** Python 3.12, LinkML, Pydantic, asyncpg com SQL explícito, Alembic, PostgreSQL/AlloyDB, Hindsight, pytest e Terraform (ADR 0003). Framework HTTP/MCP e motor de fluxos são decididos nas suas issues.
- **Requisitos viram testes:** cada um dos 13 requisitos do §4 vira um teste automatizado de aceitação, que roda no CI desde que existe.
- **Medição desde o começo:** traces (OpenTelemetry) e conjuntos de avaliação começam na primeira chamada de modelo, não no fim.
- **Git:** integração direta na `main` enquanto o time for o mantenedor e o agente (AGENTS.md).

## Fases

### Fase 0: Fundação e destravamentos
- Estrutura do monorepo, Compose de desenvolvimento e CI de produto (lint, tipos, testes, contrato de importação e neutralidade).
- Fixtures de referência (descritas acima) e o esqueleto dos 13 testes de requisito, marcados como `xfail`.
- **Serviços gerenciados** (Agent Gateway com Service Extensions, regiões do Agent Engine, Claude no Vertex, Gemini em southamerica-east1): não houve spike. A validação acontece nas issues que os usam (K11, K31, K34). Se algo não se confirmar, o adaptador local passa a ser o caminho principal.
- **Memória:** decidida no ADR 0001 (concluído).
- **Abrir já as frentes externas** (prazo longo, só bloqueiam a Parte B): permissões no Entra ID e contas de serviço, API do portal de alocação e horas, modelo de acesso ao Granola, política de transcrições com cliente e residência de dados (jurídico).
- **Saída:** `docker compose up` sobe a base, o CI roda, os ADRs 0001–0003 estão aceitos e as frentes externas têm dono e status.

**Fatia 1 (atravessa F0–F2):** PXOS-1 (K01), as sub-issues PXOS-47 a 51 (partes de K04, K05, K06, K08 e K09), PXOS-7 (K07) e, na BRQ@work, o pacote de contexto de trabalho (PXOS-46). **Saída:** um compromisso é proposto com evidência, aprovado pelo papel declarado, lido em duas datas e corrigido sem perder histórico; o pacote fixture de outro domínio faz o mesmo ciclo; nenhum tipo de domínio aparece em `pxos-kernel/`.

### Fase 1: Ontologia e geração de código
- Ontologia base em LinkML (Organização, Contrato, Ator, Papel, Evento, Evidência, Métrica, Resultado e suas ações), mais o pacote de contexto de trabalho (na distribuição BRQ@work) e um pacote fixture de outro domínio.
- Camadas: base, pacote e extensão por instalação, com versionamento por camada.
- Geradores no CI produzem: schemas de extração (JSON Schema/Pydantic), tools MCP, views tipadas do banco, modelos para agentes e definições de cards.
- Formato de manifesto de módulo e de distribuição, com validador.
- **Saída:** mudar um YAML regenera os 5 artefatos de forma determinística, com testes de snapshot. Uma mudança incompatível sem migração faz o CI falhar.

### Fase 2: Estado canônico, instalação e identidade
- Estado canônico governado: proposta imutável → aprovação presa ao digest → fato versionado com **duas datas** → correção e invalidação, sobre o contrato do spike de governança. Outbox na mesma transação.
- Instalação dedicada com a sua política; permissões internas por RLS. O contexto (Hindsight) fica isolado pela instalação e pelo escopo do servidor.
- Exclusão real (estado canônico, contexto no Hindsight, fatos derivados e páginas), com registro de que houve a exclusão. Política de retenção por instalação.
- Identidade de pessoas, agentes e atores externos: modelo de papéis e delegações. Externos ficam sem acesso às tools de leitura.
- **Saída:** passam os testes dos requisitos 3 (fonte), 4 (credencial de outra instalação recusada e leitura restrita negada pelo banco), 5 (identidade) e 11 (a parte de exclusão e retenção).

### Fase 3: Acesso a modelos e medição base
- Ponto único de chamada: pseudonimização (Sensitive Data Protection, ou um adaptador local com Presidio), roteamento por residência da instalação e inspeção (Model Armor, ou um stub local).
- Traces com custo, modelo, região e instalação (OpenTelemetry → Cloud Trace e BigQuery, ou Jaeger e Postgres em local).
- Harness de avaliação: conjuntos de referência rodam a cada mudança de prompt, modelo ou ontologia.
- **Saída:** uma instalação que exige residência no Brasil nunca chega ao endpoint global (teste). Dados pessoais saem pseudonimizados. Toda chamada gera trace.

### Fase 4: Ingestão e framework de conectores
- Contrato de conector: leitura, mapeamento, ações, acesso e instalação.
- Três modos de leitura: aviso de mudança com leitura incremental, captura de mudanças (Datastream ou um adaptador local com logical replication/Debezium) e leitura periódica com diff.
- Fila de eventos, idempotência, reconciliação periódica, carga inicial e descarte do que não tem vínculo.
- Registros operacionais vão direto para o estado vivo e para a base analítica, sem modelo.
- **Saída:** os dois conectores falsos rodam. Reenviar e embaralhar eventos não gera duplicatas (requisitos 2 e 8).

### Fase 5: Canais e fila de revisão
- Abstração de canal: entregar mensagem e card, receber pedido e aprovação. Inclui o canal falso de referência.
- Fila de revisão com cards gerados da ontologia, roteamento para o dono, prazo, substituto ou gestor e expiração.
- **Saída:** um card criado pelo kernel chega ao canal falso, é aprovado ou expira, e o resultado volta como evento.

### Fase 6: Proposta canônica e identidade
- A extração de contexto é do Hindsight (ADR 0001); não se reconstrói extrator, resolvedor ou reconciliador. Esta fase faz: consumidor com triagem e retenção no contexto, propostas canônicas com evidência literal validada em código, identidade canônica (chave determinística, aliases, restrição de candidatos, fila humana) e roteador por confiança sobre o estado canônico.
- Conjunto de avaliação com transcrições sintéticas anotadas.
- **Saída:** a avaliação mede precisão de extração e precisão de junção, e a junção fica em 99% ou mais nas fixtures. Fato sem evidência literal é descartado. Risco e mudança de escopo sempre viram card.

### Fase 7: MCP, API e gateway de ação
- Autenticação com OIDC genérico (Entra ID fica na Parte B; em local, um IdP falso como Keycloak).
- Catálogo de tools gerado: leitura (search, get_context, timeline, list_commitments, get_page) e uma tool por ação.
- Serviço de política: ação × papel × parâmetros × fase de autonomia × regras do módulo.
- Encaminhador para a fila, executor como único caminho de escrita, caminho síncrono para ações pré-aprovadas, log de auditoria e credenciais (Secret Manager ou um adaptador local).
- **Saída:** passam os testes dos requisitos 1 (o mesmo MCP serve pessoa e agente), 6 (ação irreversível sempre aprovada) e 7 (latência p95 do caminho síncrono dentro da meta definida no ADR).

### Fase 8: Agentes, gatilhos e fluxos
- Runtime de agentes (ADK, com Agent Engine ou execução local), identidade por agente, fases de autonomia e métricas de progressão. Leitura com a delegação da pessoa.
- Gatilhos por agenda (horário da pessoa ou do papel) e por evento (mudanças no estado vivo). Fluxos longos com etapas, prazos e checagens humanas.
- Agente de referência sobre as fixtures.
- **Saída:** o agente de referência é acionado por agenda e por evento, lê via MCP e age via gateway na fase 1. A progressão de fase só acontece por métrica.

### Fase 9: Manutenção, base analítica e medição de resultado
- Job diário: deduplicação, conflitos, envelhecimento, páginas narrativas regeneradas com citação dos fatos, propostas de PR à Constituição.
- Base analítica (BigQuery, ou DuckDB/Postgres em local): histórico em volume, um modelo analítico de referência chamado como tool.
- Medição de resultado: linha de base, indicadores por contrato e trilha auditável.
- **Saída:** passam os testes dos requisitos 9 e 10. A página narrativa é regenerada quando um fato muda.

### Fase 10: Apps e implantação → **Marco: kernel completo**
- Hospedagem de apps: banco próprio por app, espelhamento de fatos no estado vivo e acesso só por MCP, API e canais. Kit de construção de apps com um app de referência.
- Ciclo de vida de módulos e distribuições por instalação (instalar, atualizar, remover, regenerar), testes de distribuição contra uma versão nova do kernel e permissões por módulo.
- Terraform para a instalação dedicada (projeto GCP por cliente). O modo compartilhado fica adiado.
- **Saída:**
  - os 13 testes de requisito passam;
  - a "distribuição de referência" instala do zero em local e em um projeto GCP de homologação;
  - o requisito 13 é verificado: nenhum código de domínio no kernel.

### Fase 11+: BRQ@work (Parte B, sequência grossa)
Para começar, precisa dos gates de TI e jurídico da Fase 0 resolvidos.
1. Pacote de projetos e operação, conector do Microsoft 365 (Graph: SharePoint/OneDrive delta, canais, calendário, renovação de assinaturas) e cadastro de projeto.
2. Conector do Granola (conforme o modelo de acesso decidido) e mapeamento de reunião para projeto por calendário e série.
3. Canal Teams (bot e cards) e Claude Enterprise via MCP, com Entra ID.
4. Escriba pós-reunião, em fase 1. **Piloto com 1 ou 2 projetos.**
5. Conector do Bud e conector do portal (se houver API; sem API, o agente só sugere).
6. Briefing do dia e pré-reunião, status semanal e programação de alocação.
7. App de visão de carteira. Expansão para cerca de 250 pessoas de PX, acompanhando as métricas do §14.

## Rastreabilidade

**Contêineres (§5) → fase**

| Contêiner | Fase |
|---|---|
| Repositório Git (ontologia, CI) | 1 |
| Estado vivo | 2 |
| Acesso a modelos | 3 |
| Ingestão e conectores | 4 |
| Canais | 5 |
| Extração e identidade | 6 |
| MCP e API | 7 |
| Gateway de ação | 7 |
| Agentes | 8 |
| Gatilhos e fluxos | 8 |
| Manutenção | 9 |
| Base analítica | 9 |
| Medição e resultado | 3 (base) → 9 (resultado) |
| Apps | 10 |

**Requisitos (§4) → fase do teste verde**

| Requisitos | Fase |
|---|---|
| 3, 4, 5 | 2 |
| 11 | 2 (exclusão) + 3 (pseudonimização e residência) |
| 2, 8 | 4 |
| 1, 6, 7 | 7 |
| 9, 10 | 9 |
| 12, 13 | 10 (auditoria de adaptadores e de fronteira) |

**Questões em aberto (§16) e pontos jurídicos (§13) → gate**

| Questão | Começa | Bloqueia |
|---|---|---|
| Construir ou adotar a memória | resolvida (ADR 0001) | — |
| Residência de inferência | F0 (spike + jurídico) | F3 (desenho), F11 (produção) |
| Compartilhada vs. dedicada | dedicada como padrão; compartilhada adiada | F10 (só se surgir demanda) |
| Governança da fronteira do kernel | resolvida (ADR 0002) | — |
| Permissões do Entra ID e contas de serviço | F0 (TI) | F11.3 |
| API do portal | F0 (TI) | F11.5 |
| Modelo de acesso ao Granola | F0 | F11.2 |
| Política de transcrições com cliente (LGPD) | F0 (jurídico) | F11.2 / piloto |
| Camada conversacional de atendimento | adiada | fora deste plano (outra distribuição) |
| Modelo de contrato das distribuições de cliente | adiada | fora deste plano (só define a linha de base da F9) |

## Verificação

- O CI roda lint, tipos, testes unitários e a **suíte dos 13 requisitos** contra as fixtures, a cada commit.
- Avaliação contínua: os conjuntos de referência de extração e junção rodam a cada mudança de prompt, modelo ou ontologia, com limiares.
- Ponta a ponta local: `docker compose up`, injetar eventos dos conectores falsos e verificar fatos no estado vivo, card no canal falso, aprovação, ação executada e auditoria registrada.
- O marco do kernel é validado instalando a distribuição de referência num projeto GCP de homologação. Isso só acontece com o seu pedido explícito.

## Próximo passo

A fatia 1 foi concluída em 13/11/2026: PXOS-1, PXOS-47 a 51, PXOS-7 e PXOS-46, com o teste de
saída verde no CI contra Postgres. A suíte de aceitação (`pxos-kernel/tests/acceptance/`) tem
um teste por requisito do §4; o req. 3 está verde e os demais são falhas esperadas que nomeiam
a issue que os entrega. O escopo da próxima fatia é decidido com o mantenedor, e cada fase
começa com confirmação explícita.
