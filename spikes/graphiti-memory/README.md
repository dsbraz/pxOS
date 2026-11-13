# Spike de memória do pxOS

Experimento descartável e independente do produto. Hipótese: Graphiti, guiado pela ontologia,
consegue atender à memória do pxOS sem construir outro extrator, resolvedor ou reconciliador?
Compatibilidade com Neo4j, por si só, não aprova essa hipótese.

Conclusão executada: [ADR-001](reports/ADR-001.md). A hipótese de memória canônica única não foi aprovada.

## Responsabilidades

| Componente | Papel |
|---|---|
| LinkML | Ontologia declarativa; geração nativa de modelos Pydantic |
| Graphiti 0.31.2 | Extração, resolução, reconciliação temporal e recuperação |
| Neo4j Community 5.26.0 | Um grafo local, exclusivo do experimento |
| Vertex AI | Gemini 3.8 Flash (`global`) e embedding 001 (`us-central1`, 768 dimensões) |
| CLI Python | Execução, proveniência dos experimentos e avaliação |
| AlloyDB | PostgreSQL operacional escolhido para o produto; fora desta primeira implementação |

Sem Mem0, LangExtract, pgvector ou Zep comercial. Não há implementação de produto, API ou UI.
O pacote Graphiti traz bibliotecas OpenAI transitivas, mas todos os clientes usados são Gemini/Vertex.
Modelos e regiões são explícitos; falha do modelo configurado não aciona fallback silencioso.

## Ambiente

Projeto GCP compartilhado pelos experimentos: **`pxos-spikes`**, organização `getbud.co`,
faturamento da Bud. O projeto `bud2-saas-homolog` não é usado. Não é alterado o projeto ativo
do gcloud e não são lidas credenciais ADC. `spike-runner@pxos-spikes.iam.gserviceaccount.com`
é impersonada com tokens temporários. Não há chave de conta de serviço gravada em arquivo.
As permissões da conta de serviço são `roles/aiplatform.user` e
`roles/serviceusage.serviceUsageConsumer` no projeto dos spikes.

Execute nesta pasta, com Python 3.12, uv, Docker Compose e gcloud:

```sh
uv sync --frozen
cp .env.example .env
# Preencha SPIKE_GCP_PROJECT=pxos-spikes e SPIKE_GCP_ACCOUNT com a conta autorizada.
gcloud auth login
# A conta autorizada precisa de roles/iam.serviceAccountTokenCreator na spike-runner.
docker compose up -d --wait
uv run --frozen python -m spike generate
uv run --frozen python -m spike doctor
SPIKE_TEST_NEO4J=1 uv run --frozen pytest -q
uv run --frozen python -m spike doctor --live
```

`doctor` é local; `doctor --live` faz inferência real com o Pydantic gerado e verifica a dimensão
do embedding. As verificações locais incluem o filtro temporal em Neo4j, sem simular extração.
`httpx` é dependência explícita porque Graphiti 0.31.2 o importa, mas a resolução de dependências
com os SDKs atuais não o instalou transitivamente. Tudo está registrado em `uv.lock`.

## Experimento

```sh
uv run --frozen python -m spike run --variant both --repetitions 3 --reset --output runs/comparison
```

São três rodadas de cada variante, sempre com estado limpo. `--reset` verifica o nome do projeto
Compose e o vínculo da porta antes de limpar apenas esse Neo4j. Não rode duas avaliações ao mesmo
tempo. Cada rodada grava seu estado antes de a próxima começar. A pasta de saída deve ser nova;
erros preservam evidências e encerram a execução. `ingest` é um alias de `run`.

Os 12 episódios sintéticos cobrem quatro pessoas, duas organizações, dois projetos, homônimos,
alias explícito, menção ambígua, mudança de dono e prazo, correção retroativa, chegada fora de ordem
e um fato com fontes públicas e restrita. A ordem de chegada é fixa, separada da data de referência.
Os resultados esperados ficam nas fixtures e não são enviados ao modelo.

O mesmo conteúdo e os mesmos clientes são usados nas duas variantes. A diferença são
`entity_types`, `edge_types` e `edge_type_map`. O registro de tipos é pequeno e explícito em
`spike/ontology.py`. `spike/generated.py` é gerado integralmente pelo LinkML, com metadados de
implementação omitidos por uma opção nativa do gerador. Não editar esse arquivo manualmente.

Após ingerir, a CLI consulta os oito casos, compara uma consulta histórica antes e depois de uma
retificação, reenvia um episódio para observar o replay nativo e remove a fonte restrita. Não há
cache que oculte duplicação nem filtros que escondam informação restrita no experimento.
`principal` nas fixtures é uma expectativa de autorização, **não** um controle aplicado por Graphiti.

```sh
uv run --frozen python -m spike query 'Quem é responsável pelo CMP-1?' \
  --valid-at 2026-01-05T13:00:00+00:00 --output runs/query-manual
uv run --frozen python -m spike report runs/comparison/ontology-1
```

`query` consulta o grafo da última rodada, que já passou pelo teste de exclusão. Para revisar o
estado anterior, use os snapshots. `--known-at` recebe o instante real de ingestão registrado
nos checkpoints, não a data histórica da reunião. O filtro usa intervalos semiabertos: início
inclusivo e fim exclusivo. A correção precisa passar também pela comparação de conhecimento;
ter quatro timestamps nas relações não basta.

## Evidências e leitura dos resultados

Cada rodada salva:

- `manifest.json`: versões, modelos, regiões, hashes dos inputs, imagem e status.
- `e01.json` a `e12.json`: estado completo após cada ingestão e latência.
- `query-*.json`: recuperação nativa, sem uma segunda chamada para redigir uma resposta.
- `before-correction.json` e `after-correction-as-known-before.json`: consulta bitemporal.
- `after-replay.json` e `after-delete.json`: comportamento nativo e derivados após exclusão.
- `calls.jsonl`: modelo, região, duração, uso informado pelo provedor e erros de cada chamada SDK.
- `review.json`: ficha de revisão semântica com fontes e resultados esperados.
- `observations.json`, `metrics.json`, `report.md`: verificações e resumo.

`null` significa não avaliado, nunca zero ou sucesso. O relatório só calcula precisão e cobertura
quando os fatos retornados foram anotados em `review.json`; a precisão é a fração de fatos corretos
entre os fatos avaliados, e a cobertura é a fração dos fatos esperados recuperados. Acurácia usa
somente casos revisados e informa esse denominador. Não extrapolar esta amostra para produção.
Para evidência literal, conferir trecho e fonte, não apenas a existência de UUIDs de episódios.

Contadores de tokens são os retornados pelo provedor; embeddings podem não informar uso.
Invocações SDK não contam retries HTTP internos. Não há cálculo monetário sem tabela de preços
verificada. A medição não registra prompts, tokens de autenticação ou credenciais.

## Critério de decisão

Classificar cada requisito como nativo, configuração, integração pequena ou não atendido.
Aprovação exige inspecionar e aprovar a **mutação exata**, inclusive invalidações, antes de gravá-la.
Permissão exige impedir vazamento em relações, atributos, episódios e resumos derivados.
A ausência dessas capacidades não será resolvida com fork privado ou segundo pipeline neste spike.

Saídas possíveis: adequado como memória canônica; candidato apenas a projeção derivada (nova decisão
necessária); inadequado. Requisitos obrigatórios não atendidos impedem recomendar memória canônica.
Um resultado negativo ainda conclui a hipótese. Teste não executado permanece inconclusivo.

## Parar e limpar

```sh
docker compose stop
# Remove apenas os recursos locais deste Compose, incluindo os dados sintéticos:
docker compose down --volumes
```

Arquivos em `runs/` permanecem para auditoria. Não exclua o projeto GCP ao limpar este spike: ele é
reutilizável pelos próximos. Neo4j só escuta em `127.0.0.1:17474` e `127.0.0.1:17687`.
Não existem serviços de aplicação hospedados no GCP; Vertex é chamado sob demanda.

## Referências verificadas

- [Graphiti](https://github.com/getzep/graphiti/tree/v0.31.2)
- [Tipos customizados](https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types)
- [Gerador Pydantic do LinkML](https://linkml.io/linkml/generators/pydantic.html)
- [Embeddings no Vertex](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings)
