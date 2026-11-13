# ADR 0002 — Fronteira entre kernel e distribuição

**Status:** aceito em 13/11/2026. Responde à questão do PRD (§16) "governança da fronteira do kernel".

## Contexto

O PRD propõe que uma capacidade entre no kernel quando duas ou mais distribuições
precisam dela. Com uma distribuição só (BRQ@work), esse critério nunca dispara.
Precisamos de uma regra que funcione agora.

## Decisão

**Regra de natureza.** Pergunta: "esse código mudaria se o cliente fosse uma rede de
varejo em vez da BRQ?"

- **Não mudaria → kernel** (`pxos-kernel/`). Mecanismos sem vocabulário de domínio.
- **Mudaria → distribuição** (`brq-at-work/`). Tudo que fala a língua de um domínio ou de
  um sistema específico.

| Kernel | Distribuição BRQ@work |
|---|---|
| Ontologia base do PRD e metamodelo de ação | Pacotes de domínio (contexto de trabalho, projetos e operação) |
| Estado canônico, governança, bitemporalidade | Quem aprova o quê, como configuração |
| Mecanismo de extração e validação de evidência | Regras e prompts de extração |
| Contrato de conector, fila, idempotência | Conectores M365, Granola, Bud, portal |
| Abstração de canal, fila de revisão, cards gerados | Canal Teams, texto e UX dos cards |
| MCP, política, executor, auditoria, identidade | Agentes, Constituição BRQ, app de carteira |
| Adaptador do Hindsight, gateway de modelos | — |

**Desempate:** na dúvida, vai para a distribuição. Promover para o kernel depois é
barato; remover do kernel é caro.

**Árbitro:** o mantenedor. Cada caso cinzento decidido vira uma linha na tabela abaixo.

**Revisão:** quando existir a segunda distribuição, o critério do PRD (duas ou mais
distribuições) volta a valer para promoções.

## Garantias automáticas

- `brq-at-work` depende de `pxos-kernel`; nunca o contrário (contrato de importação no CI).
- Teste de neutralidade: o código e a ontologia do kernel não contêm termos de domínio.
- Um pacote fixture de outro domínio passa pelos mesmos fluxos nos testes do kernel.

## Casos decididos

| Data | Item | Lado | Motivo |
|---|---|---|---|
| 13/11/2026 | Pacote de contexto de trabalho | Distribuição | Vocabulário de domínio |
