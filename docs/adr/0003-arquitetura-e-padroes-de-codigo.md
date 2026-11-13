# ADR 0003 — Arquitetura e padrões de código

**Status:** aceito em 13/11/2026.

## Contexto

O kernel vai ser construído por um time de duas pessoas (mantenedor e agente), mas
precisa durar e ser operado por instalação dedicada por cliente. Os padrões abaixo
valem para `pxos-kernel/` e `brq-at-work/`. Eles derivam do que os spikes provaram e das
regras do `AGENTS.md` (simplicidade, mudanças cirúrgicas).

## Decisões

### 1. Monólito modular

O kernel é **um pacote Python e um processo implantável** por instalação. Os 13
contêineres do PRD (§5) são **módulos internos** com fronteira explícita, não
microsserviços. Um módulo só vira processo separado quando houver motivo medido
(escala, isolamento de falha, ciclo de deploy).

```
pxos-kernel/src/pxos_kernel/
├── ontology/      base, metamodelo, carga de pacotes, geração
├── state/         estado canônico: propostas, revisões, fatos, outbox
├── identity/      atores, papéis, delegação, contexto de sessão
├── context/       porta e adaptador do Hindsight
└── ...            cada contêiner nasce quando sua issue começa
```

Regras de dependência entre módulos ficam declaradas no `import-linter` e rodam no CI.
Um módulo expõe uma API pública no seu `__init__.py`; os demais não importam internos.

**Encaixe entre kernel e distribuição.** A **distribuição é a raiz de composição**: o
processo implantável é iniciado por `brq-at-work`, que importa o kernel e registra nele os
seus pacotes (modelos gerados, manifestos e configuração) por uma API pública do kernel.
O kernel nunca importa código da distribuição, nem dinamicamente por nome; ele só conhece
o que recebe no registro. Cada pacote guarda o seu LinkML e o código gerado a partir dele
na própria pasta, dentro do pacote Python, para que o código gerado seja importável e
a ontologia vá junto na distribuição do pacote (`pxos_kernel/ontology/base/` para a base,
`brq_at_work/ontology/<pacote>/` para os pacotes da distribuição). Os testes do kernel
registram o pacote fixture da mesma forma.

### 2. O banco é o guardião

Invariantes que protegem dados ficam no PostgreSQL, não só na aplicação. O spike de
execução provou esse caminho.

- Isolamento interno por **RLS**, com o ator da sessão definido por `SET LOCAL` na transação.
- Histórico só acrescentado: o papel da aplicação não tem `UPDATE`/`DELETE` nas tabelas de
  fatos; o expurgo é uma função restrita e auditada.
- Unicidade, idempotência e concorrência por constraints, chaves únicas e locks.
- Migrações versionadas com **Alembic**, escritas em SQL explícito (`op.execute`), sem
  autogeração a partir de ORM. O SQLAlchemy entra só como dependência do Alembic.

Teste correspondente: com um bug proposital na aplicação, o banco ainda nega.

### 3. Núcleo funcional, casca imperativa

Regras de decisão (digest, validação de proposta, elegibilidade de aprovador, política,
resolução temporal) são **funções puras**, testadas sem banco. O I/O (banco, Hindsight,
modelos) fica numa casca fina que chama essas funções. Isso mantém as regras legíveis e
os testes rápidos.

### 4. Portas e adaptadores só nas bordas externas

Interfaces (`typing.Protocol`) existem apenas para dependências externas trocáveis:
Hindsight, provedores de modelo, fila, segredos, motor de fluxos. Cada porta nasce na
issue que tem o primeiro consumidor, com um adaptador real e um falso para testes.
Código interno não ganha interface "por via das dúvidas".

### 5. Acesso a dados

`asyncpg` com **SQL explícito**, agrupado por módulo em funções de repositório. Sem ORM.
Motivos: RLS e `SET LOCAL` ficam visíveis, o SQL é o contrato que revisamos, e os spikes
já funcionam assim. Modelos Pydantic gerados do LinkML validam o que entra e sai.

### 6. Contratos tipados

- A ontologia LinkML é a fonte; Pydantic e JSON Schema são gerados com os geradores
  nativos, de forma determinística, e conferidos por teste de snapshot.
- Pydantic v2 nas bordas (API, MCP, pacotes, configuração). Dentro do núcleo, tipos simples
  e `dataclass(frozen=True)` quando bastar.
- Tipagem estática estrita (`mypy --strict`) em código não gerado.

### 7. Erros

Falhas são explícitas. Uma hierarquia pequena por módulo (ex.: `ProposalRejected`,
`NotAuthorized`, `StaleRevision`) herdando de `PxosError`. Sem `except` genérico, sem
fallback silencioso, sem retorno `None` para indicar erro.

### 8. Eventos

Toda mudança no estado canônico grava um evento numa tabela **outbox** na mesma
transação. A publicação na fila é um passo separado e idempotente.

### 9. Configuração e segredos

`pydantic-settings` lendo variáveis de ambiente, validadas na inicialização. Nada de
segredos no repositório; `.env.example` documenta as variáveis.

### 10. Idioma e nomes

- Identificadores de código **e de schema** em **inglês**, inclusive nomes de classes e
  slots LinkML dos pacotes de domínio (`Commitment`, `WorkStream`, `owner`). Esses nomes
  entram em payloads gravados e digests, então são escolhidos uma vez.
- O vocabulário em português fica nos rótulos (`title` e `description` do LinkML), que
  alimentam cards, tools e mensagens.
- Documentação, ADRs e mensagens ao usuário em português.
- Python: `snake_case` para módulos e funções, `PascalCase` para classes.

### 11. Testes

- **Unitários** no núcleo funcional, sem I/O.
- **Integração** contra PostgreSQL real do Compose; sem mock de banco.
- **Aceitação**: um teste nomeado por requisito do §4 (`test_req_01` … `test_req_13`),
  `xfail` até a issue que o entrega.
- **Neutralidade**: o pacote fixture de outro domínio passa pelos mesmos fluxos.
- Adaptadores externos têm teste de contrato com o falso; chamadas reais só sob opt-in.

### 12. Ferramentas

Python 3.12, `uv` (workspace com um lockfile), Ruff (lint e formatação), mypy, pytest,
import-linter, Docker Compose com portas em loopback. Uma ferramenta por responsabilidade.

## Fora deste ADR

Framework HTTP/MCP, motor de fluxos (Temporal ou Cloud Workflows), observabilidade e
runtime de agentes são decididos nas issues que os introduzem.
