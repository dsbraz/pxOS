# Spike Hindsight com AlloyDB

Experimento separado do produto e do [spike Graphiti](../graphiti-memory/README.md).
Testa se Hindsight pode assumir extração, resolução, consolidação e recuperação da memória
com PostgreSQL gerenciado, usando pontos públicos de extensão e sem outro motor de memória.
A hipótese só é aprovada se as evidências atenderem aos requisitos do pxOS; conseguir conectar
Hindsight ao AlloyDB é o primeiro teste, não a conclusão.

## Ambiente

- Hindsight API slim e cliente 1.2.1, Python 3.12, dependências em `uv.lock`.
- Projeto GCP `pxos-spikes`, reutilizável; cluster exclusivo `hindsight-spike`, região `us-central1`.
- AlloyDB PostgreSQL 16, instância `primary`, 2 vCPUs, zonal, banco `hindsight_spike`.
- pgvector, busca textual nativa em português e combinação RRF, sem outro reranker.
- Gemini `gemini-3.8-flash` no Vertex global; `gemini-embedding-001` em `us-central1`, 768 dimensões.
- API e Auth Proxy locais em `127.0.0.1:18888` e `127.0.0.1:15432`.
- Auth Proxy 1.17.2 com IP público e IAM, sem redes externas autorizadas.
- ADC isolado impersonando `spike-runner@pxos-spikes.iam.gserviceaccount.com`; nenhuma chave de conta de serviço.

São dados sintéticos. Endpoint global e banco nos EUA não validam uma política de residência brasileira.
A aplicação local acessa o banco remoto; as latências incluem essa rede e não são benchmark de produção.
Os arquivos `.secrets/`, `.tools/` e `runs/` estão ignorados. Não publicar credenciais ou logs de serviço.

## Hipóteses e medição

As 12 fontes e oito perguntas são cópias byte a byte das fixtures do Graphiti. `expected` é gabarito
exclusivo da avaliação e nunca é enviado ao modelo. Cada execução cria um banco de memória novo.

1. `generic`: extração padrão do Hindsight.
2. `labels`: vocabulário nativo para pessoa, organização, projeto e compromisso, com atributos;
   mantém entidades livres habilitadas. Não é um schema LinkML nem impõe chaves determinísticas.
3. `review`: uma extensão pública rejeita todos os fatos de uma fonte e registra a proposta;
   a prévia de extração também é chamada, sem persistência dos fatos.
4. `purge`: duas fontes isoladas verificam a exclusão também dos registros de chamadas ao modelo.

A ingestão usa `document_id` estável, data da fonte, versão e tag de acesso. A avaliação espera
as consolidações assíncronas antes de avançar. Salva fatos, entidades, vínculos das Anas, respostas,
fontes, chamadas, tempos, replay e exclusão. Falhas de operação interrompem a execução.

`recall` recupera contexto e `reflect` responde com o motor nativo. A coexistência de afirmações
históricas na busca não é considerada erro por si só. `query_timestamp` ancora a pergunta;
não é um filtro bitemporal. A mesma pergunta antes e depois da retificação mede mudança da resposta,
não prova uma consulta ao estado conhecido em uma data anterior.

`SpikePolicy.resolve_tag_scope` impõe `access:public` no servidor para a credencial do leitor.
Os testes incluem uma tentativa de sobrescrever esse escopo pelas tags da requisição, grafos,
listagens e leitura direta da fonte restrita, com controle positivo pelo administrador.
É uma extensão de experimento, não uma política completa de autorização para todos os endpoints.
O teste não valida isolamento multitenant por RLS ou identidade de usuários de produção.

O replay repete a mesma fonte e versão. A exclusão remove e08, verifica recuperação e memórias,
e procura resíduos no armazenamento com `spike.audit`. Fatos apoiados em outras fontes devem sobreviver.
As evidências ficam em `runs/`; a decisão e as limitações ficam em `reports/ADR-001.md`.

## Executar no ambiente preparado

```sh
cd spikes/hindsight-memory
uv sync --frozen
uv run python -m spike.runtime start
uv run python -m spike.doctor
uv run python -m spike.experiment --variant generic
uv run python -m spike.experiment --variant labels
uv run python -m spike.experiment --variant review
uv run python -m spike.experiment --variant purge
uv run python -m spike.audit NOME_DO_BANCO_DA_EXECUCAO
uv run pytest -q
uv run ruff check spike tests
```

Se a instância estiver parada, antes de iniciar o runtime:

```sh
gcloud alloydb instances update primary --cluster=hindsight-spike --region=us-central1 --project=pxos-spikes --activation-policy=ALWAYS
```

Aguardar `state=READY` antes de iniciar o runtime. O comando de atualização pode retornar
antes de a transição terminar; conferir com:

```sh
gcloud alloydb instances describe primary --cluster=hindsight-spike --region=us-central1 --project=pxos-spikes --format='value(state,activationPolicy)'
```

## Renovar o login isolado

Concluir o login no próprio terminal. O segundo comando prepara a impersonação e preserva as
chaves locais existentes da API. O ADC global e o projeto ativo do gcloud não são alterados.

```sh
CLOUDSDK_CONFIG=/tmp/pxos-spikes-auth gcloud auth application-default login --project=pxos-spikes
uv run python -m spike.auth --source /tmp/pxos-spikes-auth/application_default_credentials.json
```

A conta autenticada precisa de `roles/iam.serviceAccountTokenCreator` sobre a conta do spike.
A conta do spike precisa de Vertex AI User, Service Usage Consumer e AlloyDB Client em `pxos-spikes`.

## Reconstituir a infraestrutura e o proxy

`cloud.py` provisiona somente os nomes dedicados declarados no arquivo. Pressupõe projeto,
faturamento, conta de serviço e APIs AlloyDB, Compute e Service Networking já habilitados.
Preservar `.secrets/database.json` enquanto o cluster existir: gerar outra senha local não altera
a senha de um cluster já criado. Não é um módulo de infraestrutura do produto.

```sh
uv run python -m spike.cloud
mkdir -p .tools
curl --fail --location https://storage.googleapis.com/alloydb-auth-proxy/v1.17.2/alloydb-auth-proxy.linux.amd64 --output .tools/alloydb-auth-proxy
chmod 700 .tools/alloydb-auth-proxy
```

## Encerrar sem apagar os dados

```sh
uv run python -m spike.runtime stop
gcloud alloydb instances update primary --cluster=hindsight-spike --region=us-central1 --project=pxos-spikes --activation-policy=NEVER
```

Parar os processos locais não para o AlloyDB. Parar a instância preserva o cluster e os dados;
armazenamento permanece provisionado e o IP público ocioso também pode gerar cobrança. O projeto compartilhado de spikes não deve ser excluído.
Backups automáticos estão desabilitados para este experimento sintético.
[Comportamento de parada do AlloyDB](https://docs.cloud.google.com/alloydb/docs/instance-start-stop-restart).

## Referências

- [Instalação e PostgreSQL suportado](https://hindsight.vectorize.io/developer/installation)
- [Configuração](https://hindsight.vectorize.io/developer/configuration)
- [Provedores de modelos](https://hindsight.vectorize.io/developer/models)
- [Código e licença MIT](https://github.com/vectorize-io/hindsight)

A receita final usa dois slots compartilhados no worker, sem reserva exclusiva para consolidação,
e persistência de prompts/respostas desabilitada (`HINDSIGHT_API_LLM_TRACE_ENABLED=false`).
A opção `HINDSIGHT_API_LLM_TRACE_DELETE_WITH_DOCUMENT=true` permanece configurada, mas sozinha
não expurgou todos os traces de reflect no ensaio; ver o ADR. As métricas continuam habilitadas. Nas duas execuções comparativas originais,
a exclusão de traces estava no padrão `false`; a prova `purge` foi executada com a opção habilitada e, depois, com traces desabilitados.
Para reproduzir essa configuração inicial de retenção, iniciar o runtime com
`SPIKE_LLM_TRACE_ENABLED=true SPIKE_DELETE_TRACES_WITH_DOCUMENT=false`. A reserva de slots inicial foi corrigida antes de concluir
a manutenção pós-exclusão; não repetir a configuração que deixa manutenção sem capacidade.

Os contratos efetivamente executados são os da versão instalada e fixada no lockfile.
