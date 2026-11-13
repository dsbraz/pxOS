# Spike de execução e isolamento

Experimento local em duas instalações PostgreSQL 16 independentes (`alpha` e `beta`),
com o mesmo código e credenciais distintas. Reutiliza os contratos LinkML/Pydantic
de projetos e atendimento do spike anterior; não altera produto, roadmap ou CI.

Hipótese: somente o solicitante autenticado executa a ação exatamente aprovada,
sobre um recurso ao qual ainda tem acesso, com registro de identidade, parâmetros,
aprovador e resultado, sem atravessar instalações ou permissões internas.

## Desenho mínimo

- Uma instância por cliente, com dados e credenciais próprios.
- Papéis LOGIN `alice`, `bob`, `lead`, `agent_alice`, `agent_bob` autenticam via senha
  PostgreSQL. Cada credencial é específica da instalação e do ator.
- Delegação fixa de fixture: cada agente lê como a pessoa associada. `session_user`
  identifica o chamador; a aplicação não aceita um campo de identidade substituto.
- RLS nativa filtra recursos, propostas, efeitos e auditoria, inclusive em SELECT
  sem filtro do cliente. Agentes/pessoas não são donos nem têm BYPASSRLS.
- `propose`, `review`, `execute` são funções SECURITY DEFINER com search_path fixo,
  tabelas qualificadas e acesso público revogado. O dono NOLOGIN só concede execução
  dessas operações e leitura sujeita a RLS; não concede escrita nas tabelas.
- A revisão usa o digest de id, alvo, solicitante e parâmetros. O aprovador de
  fixture é `lead` para os dois domínios, sem autoaprovação.
- A execução confere identidade, acesso atual, aprovação, digest e parâmetros.
  Efeito e auditoria são atômicos; lock por proposta e chave única tornam a reentrega
  idempotente, inclusive concorrente.
- O efeito controlado atualiza um recurso local. O papel efetivo é `spike_owner`,
  obtido só pela função restrita; a identidade solicitante permanece na auditoria.

## Reproduzir

Nesta pasta, Python 3.12, uv e Docker:

```sh
uv sync --locked
docker compose up -d --wait
uv run --frozen pytest -q
uv run --frozen ruff check spike tests
uv run --frozen ruff format --check spike tests
uv run --frozen python -m spike
docker compose stop
```

As portas 26432 e 26433 são exclusivamente loopback. Senhas `local-<instalação>-<ator>`
e senhas de administrador no Compose são públicas e exclusivamente de fixture.
Não reutilizar fora deste ambiente. O bootstrap roda somente em volumes novos.
`stop` preserva os dados; `docker compose down --volumes` elimina os dados do experimento.
Os testes acrescentam propostas novas e não dependem dos valores iniciais dos recursos.
O runner imprime ações e trilhas dos dois domínios nas duas instalações.

## O que o resultado pode afirmar

Os testes usam autenticação e permissões reais do PostgreSQL, não booleanos simulados.
A prova cobre bloqueio de credencial cruzada, proposta de outra instalação, leitura
restrita mesmo sem filtro, falsa identidade, troca de papel, escrita direta,
aprovação inválida/pendente/rejeitada, mudança de parâmetros e reexecução concorrente.

Classificação: isolamento entre instalações e RLS são configuração nativa do banco;
aprovação exata, delegação e auditoria exigem integração própria pequena. Nenhum
motor de memória, política ou workflow adicional foi introduzido.

## Limites da prova

- É um gateway de teste em Python/SQL, não API HTTP, MCP, OIDC ou Agent Gateway GCP.
- Não testa OAuth/Secret Manager, nem ações em um fornecedor externo. A credencial
  efetiva validada é o papel de execução do banco; não existe segredo externo aqui.
- A transação local não prova exactly-once com efeitos remotos nem recuperação após
  falha de rede. Ações distintas sobre um mesmo recurso ainda podem se sobrepor.
- RLS e credenciais não isolam execução arbitrária de código: sandbox de processos,
  rede, filesystem e fuga de container não são testados.
- Administradores e dono do banco estão na fronteira confiável. A prova não isola
  um administrador malicioso nem protege contra roubo de credenciais válidas.
- Pydantic valida os tipos na entrada Python; SQL direto pode propor JSON arbitrário,
  mas continua exigindo aprovação exata. Não há validação completa LinkML dentro do banco.
- As regras e a delegação são fixtures estáticas, não um sistema de políticas completo.
- Falhas negadas retornam erro; a auditoria persistente registra transições aceitas
  e efeitos, não todas as tentativas negadas.
- Não valida AlloyDB ou Hindsight ao vivo. A integração real do ciclo de ontologia
  anterior também continua pendente. A stack de produto não é aprovada por este teste.

Demais validações de ingestão, qualidade, desempenho e recuperação permanecem na
aceitação do kernel, conforme a sequência acordada.
