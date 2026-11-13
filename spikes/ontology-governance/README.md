# Spike de ontologia e governança

Experimento executável separado do produto. Stack escolhida: AlloyDB + Hindsight.
Este spike testa a fronteira entre contexto recuperável e fatos tipados aprovados,
com o mesmo fluxo para dois pacotes pequenos. Não implementa o kernel.

## Responsabilidades

- **Hindsight:** memória contextual, extração e recuperação. O spike recebe uma
  referência de contexto e evidência; não cria outro extrator ou reconciliador.
- **AlloyDB/PostgreSQL:** propostas imutáveis na API do experimento, decisões de
  revisão e versões confirmadas. Schema exclusivo `ontology_governance_spike`;
  nenhuma leitura ou escrita nas tabelas internas do Hindsight.
- **LinkML:** fonte dos tipos de domínio; geração Pydantic nativa. Manifestos dos
  pacotes declaram o tipo, a versão e os aprovadores sintéticos.

`projects` contém um compromisso (responsável e prazo), aprovado por `project-lead`.
`support` contém um ticket (atendente e prioridade), aprovado por `support-lead`.
O serviço de governança não conhece esses tipos nem contém regras específicas deles.

## Contrato demonstrado

1. Propor valida o payload pelo pacote e exige autor, entidade, início de vigência
   e evidência (`source`, `quote`, `context_ref`). Ainda não existe fato confirmado.
2. A proposta fixa payload, evidência, versão e digest do pacote e versão-base do
   fato. O digest do conteúdo completo identifica exatamente o que foi revisado.
3. Aprovar exige o digest revisado e um aprovador declarado pelo pacote, diferente
   do autor. Decisão e fato são gravados na mesma transação.
4. Rejeitar registra decisão e motivo sem publicar. Uma decisão final não pode ser
   trocada. Reentrega da mesma decisão é idempotente.
5. Corrigir cria outra proposta sobre a revisão atual. Só a aprovação acrescenta
   a próxima revisão. Propostas concorrentes sobre a mesma revisão têm um vencedor;
   a outra precisa ser refeita e revisada. A versão anterior permanece intacta.
6. Consultar recebe data de validade e instante de conhecimento. As versões são
   snapshots completos a partir de `valid_from`; entre snapshots aplicáveis vence
   a maior data de vigência, e correções da mesma data usam a maior revisão conhecida.
   Não há intervalos finitos nem invalidação/expurgo neste experimento.

A referência de contexto **não aprova** fatos. Não há retorno automático das
propostas para a memória contextual, evitando que rascunhos pareçam fatos confirmados.
O exemplo usa contexto sintético declarado como `fixture:`, sem chamadas ao Hindsight
ou inferência. A extração real já pertence ao spike anterior; a integração completa
entre recuperação real, evidência literal e proposta continua sem validação aqui.

## Executar

Python 3.12, uv 0.13.7 e Docker, a partir desta pasta:

```sh
uv sync --locked
docker compose up -d --wait
uv run --frozen python -m spike
uv run --frozen ruff check spike tests
uv run --frozen ruff format --check spike tests
uv run --frozen pytest -q
```

O runner verifica os dois ciclos e imprime histórico com propostas, payloads,
aprovadores, evidências e datas. Cada execução usa entidades novas. Os testes abrem
conexões reais, inclusive duas conexões concorrentes, e falham se o banco não existir.
O container mantém os dados entre stop/start; `docker compose down --volumes` os remove.

Para mudar a ontologia, editar o pacote e executar `uv run --frozen python -m spike.generate`.
Os testes conferem geração reproduzível. Uma mudança de pacote impede aprovar propostas
anteriores: é necessário emitir nova proposta. Migração de fatos fica fora do spike.

`SPIKE_DATABASE_URL` substitui a conexão local (ver `.env.example`; exportar explicitamente,
o arquivo não é carregado automaticamente). Para AlloyDB, usar um banco exclusivo de
spike e conexão autenticada via proxy. O experimento não provisiona nem liga recursos
GCP. O usuário do banco precisa criar schema/tabelas; não usar credenciais de produto.
Testar PostgreSQL local não comprova uma execução deste ciclo no AlloyDB real.

## Aceite e limites

O aceite local cobre tipos inválidos, campos desconhecidos, proposta invisível antes
de aprovação, rejeição, aprovador incorreto, digest divergente, autoaprovação,
reentrega, mudança de pacote após proposta, correção retroativa, vigência futura, histórico, persistência após reconexão
e concorrência. Os aprovadores são identidades de fixture, não autenticação real.
A evidência é obrigatória mas sua literalidade na fonte não é verificada neste spike.
O dono do banco pode alterar as tabelas; imutabilidade é do caminho da aplicação,
não uma garantia contra acesso SQL administrativo.

## Sequência de validação

- **Agora:** ontologia e governança, isoladas nesta pasta.
- **Próximo spike:** execução e isolamento (identidade real, autorização, credenciais,
  execução de ações e fronteiras de acesso).
- **Aceitação do kernel:** migrações/compatibilidade dos pacotes (K04–K06), evidência
  literal e identidade (K26–K28), exclusão/retenção (K10), residência e proteção de
  inferência (K11–K13), busca autorizada (K16), replay de eventos (K19), expiração e
  escalonamento (K24), manutenção/páginas (K37–K38), distribuição e portabilidade
  (K42–K45). Os demais critérios de BACKLOG-KERNEL.md continuam testes de aceitação,
  sem abrir spikes adicionais por padrão. Ingestão resistente a falhas, qualidade,
  desempenho e recuperação também serão verificadas na aceitação do kernel.
