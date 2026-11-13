> Linear: projeto pxOS (brq-px), https://linear.app/brq-px/project/pxos-38c291a57da8. O issue Kn deste arquivo é o PXOS-n.

# Backlog do kernel do pxOS (F0–F10), revisão 2

**Escopo:** só o kernel, ou seja, a Parte A do PRD, o §4 e o §13 no que for do kernel. A BRQ@work (F11) fica fora.

**Regra:** cada issue implementa elementos do PRD, e cada elemento de kernel aparece em exatamente um issue (matriz no fim).

**Princípio de neutralidade:** o kernel não conhece tipos de domínio. Frente de trabalho, compromisso, risco e mudança de escopo vêm do pacote de ontologia, pelo mecanismo do K04.

## F0 · Fundação
- **K01 Monorepo, ambiente local, CI e interfaces de adaptador.** Estrutura `ontology/ constitution/ kernel/ modules/ distributions/ infra/ fixtures/ evals/`. Docker Compose com loopback (Postgres + pgvector, emulador Pub/Sub). CI com lint, tipos e testes. Interfaces de adaptador local/GCP para fila, modelos, segredos, base analítica, fluxos e agentes (req. 12). Aceite: `docker compose up` sobe e o CI fica verde.
- **K02 Dados de referência e esqueleto da suíte de aceitação.** Dados de fixture: 2 tenants, dados pessoais sintéticos, conteúdos com prompt injection e transcrições com gabarito de fatos e junções, alinhados aos conjuntos do K17. Os 13 testes de requisito (§4) nascem como `xfail`. Os módulos falsos nascem cada um no issue do seu contrato (K04, K18, K23, K34, K43). Aceite: a suíte roda no CI e cada requisito tem um teste nomeado.
- **K03 Spike: construir ou adotar a camada de memória.** Graphiti/Zep, Mem0 ou implementação própria sobre Postgres, avaliados contra duas datas por fato, invalidação, RLS, expurgo e portabilidade. Aceite: ADR aprovado. Bloqueia F2 e F6.

## F1 · Ontologia e geração
- **K04 Ontologia base, metamodelo e camadas.** Tipos e ações da base (Organização, Contrato, Ator, Papel, Evento, Evidência, Métrica, Resultado; registrar evento, registrar resultado, atribuir papel). Metamodelo de action_type: creates, approver, autonomia por fase, reversibilidade e parâmetros sujeitos a regra. Mecanismo para o pacote declarar:
  - o tipo âncora de vínculo (ex.: frente de trabalho);
  - as regras de extração;
  - as regras de roteamento (tipos que sempre vão para revisão).

  Camadas base → pacote → extensão por tenant (só propriedades a mais). Versão por camada, com migração obrigatória para mudança incompatível. Aprovação pelo dono da camada (CODEOWNERS). Pacote de fixture mínimo. Aceite: o pacote de fixture estende a base e o CI barra mudança incompatível sem migração.
- **K05 Geradores de código a partir da ontologia.** O CI gera schemas de extração, modelos para agentes, tools MCP (leitura list_* por tipo e uma tool de ação por action_type), views tipadas do banco e definições de cards. Aceite: geração determinística, com testes de snapshot.
- **K06 Manifestos de módulo e de distribuição.** Formato e validador. O módulo declara tipos, ações, agentes, conectores, aprovadores, regras de política, permissões e versão mínima do kernel. A distribuição declara módulos com versão, políticas e configurações padrão. Aceite: os manifestos de fixture validam e os inválidos são rejeitados.

## F2 · Estado vivo, tenants e identidade
- **K07 Núcleo do estado vivo.** Entidades, relações, fontes, aliases e log de ações. Só acrescenta para fatos, com duas datas por fato (mundo e sistema), versão por mudança e propriedades JSON validadas pelo schema. Caminho de expurgo controlado e auditado, que é o único destrutivo. Publicação das mudanças como eventos (outbox → Pub/Sub). Aceite: o req. 3 fica verde, nenhuma alteração destrutiva acontece fora do caminho de expurgo, e cada mudança gera evento.
- **K08 Tenants, política por tenant e RLS.** Registro e provisionamento de tenant, com a configuração da política por tenant: residência, pseudonimização, retenção, consentimento e IdP. Isolamento por RLS no banco, para pessoas e agentes. Aceite: o req. 4 fica verde (leitura entre tenants é negada mesmo com bug no código).
- **K09 Identidade de atores.** Pessoas, agentes e atores externos; papéis e tenants permitidos; delegação (o agente lê como a pessoa, e o acesso amplo fica restrito à ingestão). Externos sem acesso às tools de leitura internas. Aceite: o req. 5 fica verde.
- **K10 Consentimento, exclusão, retenção e saída do tenant.** Consentimento por tenant controla o que pode ser ingerido. A exclusão, seja apagada na origem ou pedida pelo titular, remove de fato no índice, nos fatos derivados e nas páginas, usando o expurgo do K07 e deixando um registro da exclusão. Retenção por tenant. Exportação dos dados do tenant em formato aberto e remoção do tenant. Aceite: os testes de exclusão, retenção e exportação ficam verdes.

## F3 · Acesso a modelos, medição base e busca
- **K11 Gateway de modelos e roteamento por residência.** Ponto único para toda chamada a modelo de linguagem. Escolhe modelo e região pela política do tenant (Gemini em São Paulo quando exige residência, Claude no endpoint global nos demais casos). A disponibilidade de regiões é validada aqui. Aceite: um tenant com residência BR nunca chega ao endpoint global.
- **K12 Pseudonimização.** Troca dados pessoais por marcadores antes da chamada e restaura na resposta, conforme a política do tenant (SDP, ou adaptador local). Aceite: nenhum dado pessoal das fixtures sai sem marcador. O req. 11 fica verde, junto com o K10 e o K11.
- **K13 Inspeção nas chamadas a modelo.** Model Armor (ou stub local): instruções escondidas em conteúdo ingerido, vazamento de dado sensível e resposta fora da política. Aceite: as fixtures de prompt injection são bloqueadas ou sinalizadas.
- **K14 Telemetria de chamadas.** Trace com custo, modelo, região e tenant (OpenTelemetry → Cloud Trace e base analítica). Aceite: 100% das chamadas têm trace completo.
- **K15 Base analítica: armazenamento.** Histórico operacional em volume, séries e destino dos traces e da medição (BigQuery, ou DuckDB/Postgres em local), isolado por tenant. Aceite: traces e registros das fixtures chegam à base por tenant.
- **K16 Índice de busca.** Caminho evento → trechos → embedding (via K11) → pgvector, com link para a origem e as permissões da origem aplicadas na consulta. Aceite: um trecho restrito não aparece para quem não tem permissão.
- **K17 Harness de avaliação contínua.** Conjuntos de referência rodam a cada mudança de prompt, modelo ou ontologia, com limiares que quebram o CI. Aceite: uma regressão proposital falha o CI.

## F4 · Ingestão e conectores
- **K18 Contrato e runtime de conectores.** Declaração de leitura, mapeamento, ações, acesso e instalação. Escopo mínimo por tenant. Restrição de permissão da origem carregada para o pxOS, ou o conteúdo não é ingerido. Amarração ao tenant e à entidade âncora declarada pelo pacote. Conectores falsos de conteúdo e de registros operacionais. Aceite: os conectores falsos rodam pelo contrato.
- **K19 Fila de eventos confiável.** Pub/Sub, processamento idempotente, eventos repetidos ou fora de ordem, reconciliação periódica, carga inicial do histórico e marcação de evento sem vínculo. Aceite: o replay embaralhado não gera duplicatas.
- **K20 Modo aviso de mudança e leitura incremental.** Receptor de avisos, busca do delta desde a última leitura, normalização e envio para a fila. Aceite: o req. 2 fica verde com o conector falso de conteúdo.
- **K21 Modo captura de mudanças.** Inserção, alteração ou exclusão viram eventos estruturados, mapeados direto para a ontologia sem modelo, e seguem para o estado vivo e a base analítica (Datastream, ou CDC local). Aceite: o req. 8 fica verde.
- **K22 Modo leitura periódica.** Leitura agendada com diff contra a anterior, emitindo só mudanças. Aceite: duas leituras iguais geram zero eventos.

## F5 · Canais e revisão
- **K23 Abstração de canais.** Entregar mensagens e cards; receber pedidos e aprovações; atores externos entram só pelos canais, com identidade separada. Canal falso de referência. Aceite: ida e volta pelo canal falso.
- **K24 Fila de revisão e encaminhamento.** Fila genérica, para fatos e para ações, com cards gerados da ontologia. Encaminha ao dono certo (aprovador do action_type ou dono do fato), com prazo, escalonamento para substituto ou gestor e expiração (ação expirada não executa). Toda correção é emitida como evento de aprendizado. Aceite: os cenários aprovar, corrigir, rejeitar, escalar e expirar ficam verdes.

## F6 · Extração e identidade (bloqueada também pelo K03)
- **K25 Consumidor e montador de contexto.** Lê e prioriza eventos; evento sem vínculo vai para triagem e não é extraído; contexto com o conteúdo inteiro (sem fatiar), os tipos do tenant e o estado atual com IDs. Aceite: um evento sem vínculo cai na triagem.
- **K26 Extrator e validador.** Saída estruturada pelo schema, com trecho e minuto de evidência. Regras de extração vindas do pacote, mais o descarte de assunto pessoal ou de RH. Validação em código: schema, IDs, prazos, dono e evidência literal. Inclui o conjunto de avaliação de extração. Aceite: um fato sem evidência literal é descartado e a precisão de extração é medida.
- **K27 Resolvedor de identidade em 5 níveis.** Chave determinística, tabela de aliases, restrição de candidatos, similaridade com decisão do modelo e fila humana. O tenant nunca é decidido por modelo; na dúvida não junta; junções reversíveis; correção de card vira alias. Inclui o conjunto de avaliação de junção. Aceite: precisão de junção de 99% ou mais nas fixtures, e uma correção vira alias.
- **K28 Reconciliador, roteador e gravador.** Criar, atualizar ou invalidar (nunca apagar; contradição invalida com data). Confiança por tipo com limiares calibrados e regras de revisão obrigatória vindas do pacote. Correções recalibram limiares. Gravação com fonte, autor da afirmação, confiança, status e versão. Aceite: uma contradição invalida o fato anterior e o tipo de revisão obrigatória vira card.

## F7 · MCP, API e gateway de ação
- **K29 Autenticação.** Token do IdP configurado no tenant (OIDC genérico; IdP local em dev). Identifica pessoa ou agente com papel e tenants. Aceite: um token inválido ou de ator externo é recusado nas tools internas.
- **K30 MCP e API: catálogo de tools.** Leitura genérica (search, get_context, timeline e get_page), list_* geradas por tipo e uma tool de ação por action_type (proposta → K31). Constituição servida com fonte. Mesmas permissões para pessoas, agentes e apps. Registro de uso das leituras (consumido pelo K37). MCP exposto pelo Agent Gateway, com Model Armor no tráfego dos agentes. Aceite: o req. 1 fica verde.
- **K31 Serviço de política e autonomia.** Ação × papel × parâmetros × fase de autonomia × regras do módulo dão permitir, aprovar ou negar. Fases assistido, supervisionado e autônomo; a regra do módulo limita a fase; ação irreversível sempre exige aprovação. Integração com o Agent Gateway via Service Extensions (validada aqui). Aceite: o req. 6 fica verde.
- **K32 Executor de ações, credenciais e auditoria.** Único caminho de escrita, via conectores ou servidor MCP do fornecedor atrás do Agent Gateway. Consome aprovações do K24. Credenciais OAuth de saída por agente (Secret Manager). Log de quem pediu, o que pediu, decisão, aprovação e resultado. Aceite: toda ação das fixtures tem auditoria completa.
- **K33 Caminho síncrono.** Ação pré-aprovada avaliada e executada na mesma chamada, sem fila; nada que exija aprovação entra nesse caminho. A meta de p95 é definida e medida aqui. Aceite: o req. 7 fica verde.

## F8 · Agentes, gatilhos e fluxos
- **K34 Runtime de agentes.** ADK (Agent Engine ou local). Definições de agentes e skills no Git. Identidade própria por agente, fase de autonomia, leitura com delegação e métricas de progressão (aprovação sem ajuste, incidentes) para decisão do sponsor. Agente falso de referência. Aceite: o agente de referência lê via MCP e age via gateway na fase 1.
- **K35 Gatilhos por agenda e por evento.** Agenda no horário de cada pessoa ou papel; evento a partir das mudanças publicadas pelo K07. Aceite: os dois gatilhos acionam o agente de referência.
- **K36 Fluxos de longa duração.** Etapas, prazos e checagens humanas (Cloud Workflows, ou local), usando a mesma fila e a mesma política. Aceite: um fluxo de fixture com etapa humana completa e expira corretamente.

## F9 · Manutenção, analíticos e resultado
- **K37 Job de manutenção.** Execução diária: deduplicação, detecção de conflitos e envelhecimento pelo registro de uso, com fila de revisão. Aceite: o req. 9 fica verde.
- **K38 Páginas narrativas.** Uma página por entidade do tipo âncora do pacote, regenerada do estado vivo, citando os fatos, sem edição manual. Servida por get_page. Aceite: corrigir um fato regenera a página.
- **K39 Constituição e propostas de mudança.** Estrutura da Constituição em Markdown (método, playbooks, papéis, rituais, glossário). A manutenção abre PRs de proposta. Aceite: um PR de proposta é gerado a partir das fixtures.
- **K40 Modelos analíticos como tool.** Previsão, classificação e anomalia na base analítica (BigQuery ML, Vertex, ou local), expostas como tool ao agente. Aceite: o agente de referência chama um modelo de referência como tool.
- **K41 Medição de resultado.** Custo, esforço e qualidade por agente, por entidade âncora e por contrato; linha de base e indicadores de resultado; trilha auditável pelo cliente. Aceite: o req. 10 fica verde.

## F10 · Ciclo de vida, apps e implantação → marco kernel completo
- **K42 Ciclo de vida de módulos e distribuições.** Instalar, atualizar e remover por tenant, com regeneração de schemas, tools e views. Permissões por módulo: ler tipos de outro módulo exige permissão no manifesto. Versões compatíveis com aviso e período de transição. Aceite: o req. 13 fica verde (nenhum tipo de domínio no código do kernel; a distribuição de referência é feita só de módulos).
- **K43 Apps e kit de construção.** Banco transacional por app e tenant (Cloud SQL), fatos e referências espelhados no estado vivo, acesso só por MCP, API e canais, componentes de interface, fluxos sobre o K36. App falso de referência. Aceite: o app roda e seus fatos aparecem no MCP.
- **K44 Infraestrutura como código: compartilhada e dedicada.** Terraform para os serviços do kernel. Modo compartilhado (multi-tenant) e dedicado (projeto GCP separado), a partir do mesmo código; dados nunca circulam entre instalações. Aceite: plan válido para os dois modos; apply em homologação só mediante pedido explícito.
- **K45 Atualização do kernel e marco.** Suíte por distribuição rodada contra a versão nova do kernel antes da atualização, com o mesmo processo para instalações dedicadas. A distribuição de referência é instalada do zero. Auditoria de portabilidade: LinkML, Postgres, OpenTelemetry, e serviços gerenciados só atrás de adaptadores. Aceite: os 13 requisitos verdes (o req. 12 fica verde aqui) e um upgrade simulado aprovado.

## Matriz de cobertura (PRD → issue)
| Elemento do PRD | Issue |
|---|---|
| §5 Repositório Git, CI; req. 12 (adaptadores) | K01 |
| Verificabilidade do §4 | K02 |
| §16 construir ou adotar a memória | K03 |
| §7 ontologia, camadas, versão, aprovação; metamodelo de ação | K04 |
| §7 geração (schemas, tools, views, cards, modelos) | K05 |
| §8 manifestos | K06 |
| §5 estado vivo, duas datas; §5 mudanças → Pub/Sub | K07 |
| req. 4 RLS; política por tenant | K08 |
| req. 5; §13 externos, delegação | K09 |
| req. 11 consentimento e retenção; §13 exclusão, ativo vs. dado do cliente | K10 |
| §6.4 roteamento por residência | K11 |
| §6.4 pseudonimização | K12 |
| §6.4 inspeção | K13 |
| §6.4 registro; §5 medição (traces) | K14 |
| §5 base analítica (armazenamento) | K15 |
| §5 índice de busca | K16 |
| §5 avaliação contínua | K17 |
| §6.1 contrato, escopo mínimo, permissões da origem | K18 |
| §6.1 idempotência, reconciliação, carga inicial, sem vínculo | K19 |
| §6.1 aviso de mudança | K20 |
| §6.1 captura de mudanças; req. 8 | K21 |
| §6.1 leitura periódica | K22 |
| §5 canais | K23 |
| §6.3 encaminhador; §8 revisão humana; §16 correção vira aprendizado | K24 |
| §6.2 consumidor e montador | K25 |
| §6.2 extrator e validador | K26 |
| §6.2 resolvedor | K27 |
| §6.2 reconciliador, roteador e gravador | K28 |
| §6.3 autenticação | K29 |
| §6.3 catálogo, tools de leitura e de ação; §8 Constituição pelo MCP; §13 Model Armor no Agent Gateway | K30 |
| §6.3 política e autonomia | K31 |
| §6.3 executor, credenciais, auditoria; §6.1 MCP do fornecedor | K32 |
| §6.3 caminho síncrono; req. 7 | K33 |
| §5 agentes; §8 como nasce um agente | K34 |
| §5 gatilhos | K35 |
| §5 fluxos | K36 |
| §5 manutenção; req. 9 | K37 |
| §3 páginas narrativas | K38 |
| §3 Constituição e propostas | K39 |
| §6.4 modelos analíticos | K40 |
| §5 medição e resultado; req. 10 | K41 |
| §8 ciclo de vida, versões, permissões; req. 13 | K42 |
| §8 apps, kit, dados do app | K43 |
| §5 implantação compartilhada e dedicada | K44 |
| §8 atualização do kernel; req. 12 (verificação) | K45 |
