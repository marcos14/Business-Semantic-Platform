# Plano de Implementação — Business Semantic Platform (MVP)

**Status:** Fechado para execução
**Base:** [PRD v1.0](../prds/PRD%20—%20Business%20Semantic%20Platform.md) · [Proposta Arquitetural](../architecture/proposta-arquitetural-mvp.md)
**Data:** 2026-09-01

Decisões já tomadas (não reabrir sem novo acordo):

- Monólito modular FastAPI + worker; Postgres fonte da verdade; YAML+Git como projeção canônica; event log append-only com outbox; kernel determinístico como gate único.
- Discovery/Corroboration via **harness Claude Code headless** (padrão `motor` do praxis-autonomous, portado para Python).
- Chamadas leves de LLM via **OpenRouter** (porta `LLMProvider`), modelo **Opus** em ambas as portas.
- Fila de jobs transacional no Postgres (Procrastinate).

Regra de sequenciamento: **kernel antes de agentes; UI de governança validada com candidates sintéticos antes do discovery real; métricas instrumentadas desde a Fase 1 via event log.**

---

## Fase 0 — Fundação (tamanho P)

**Objetivo:** repositório operável com CI, banco, auth e esqueleto dos dois apps.

Entregáveis:

- [ ] Monorepo: `backend/` (Python 3.12+, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, Procrastinate, ruff, pytest), `frontend/` (Next.js + TypeScript, pnpm), `canonical-repo/` (git dedicado), `docs/`.
- [ ] Docker Compose: `db` (Postgres 16 + pgvector), `api`, `worker`, `web`.
- [ ] CI (lint + testes + migração em banco efêmero).
- [ ] Migração inicial + auth e-mail/senha (argon2) + sessão JWT.
- [ ] RBAC: papéis do §7 (Viewer, Reviewer, Domain Expert, Decision Owner, Administrator) com bindings `(user, role, domain?, capability?)` (§103); middleware de autorização.
- [ ] Cadastro de domains/capabilities e usuários (API admin mínima).

**Critério de saída:** login funciona; usuário com papel escopado; CI verde; `docker compose up` sobe os 4 serviços.

---

## Fase 1 — Kernel semântico (tamanho G — corresponde ao M1)

**Objetivo:** o coração determinístico: IR, lifecycle, evidence, eventos, validação.

Entregáveis:

- [ ] Schemas Pydantic do envelope (§14) + os 14 kinds do IR (§13) + `AtomTypeRegistry` (novo kind sem migração).
- [ ] Tabelas: `sources`, `knowledge_atoms` (envelope em colunas + `body` JSONB + `lock_version`), `knowledge_atom_versions` (imutável), `evidence`, `evidence_links`, `atom_relations`.
- [ ] State machine do lifecycle (§26) — transições inválidas impossíveis; classification (§25).
- [ ] Gate de evidence: candidate automático sem evidence é rejeitado (**AC-EVI-01**).
- [ ] `domain_events` + outbox (eventos do §98 gravados na mesma transação) + consumidor de audit (§69–70).
- [ ] Semantic Linter v1 (§60): schema, referências quebradas, IDs duplicados, órfãos, transição inválida.
- [ ] API `/knowledge` (§94) com filtros do envelope; Source Registry (§10) básico.
- [ ] Optimistic locking (`lock_version` + `If-Match` → 409) (§105).

**Critério de saída:** ACs de integridade (§123) e AC-EVI-01 como testes verdes; candidate criado manualmente via API percorre o lifecycle com audit completo; linter acusa cada violação da lista do §60.

---

## Fase 2 — Confidence, Policy e Canonical (tamanho M — antecipa o M3)

**Objetivo:** roteamento automático explicável + publicação canônica versionada.

Entregáveis:

- [ ] `confidence_signals` (sinais do §28 como fatos) + heurística de independência de evidence por linhagem (§29).
- [ ] Score = função pura **versionada**, gravado com breakdown (§30) — nunca só o número.
- [ ] `policies` como dados (threshold, `human_review_required`, mín. reviewers, owner) + resolução na precedência §32; políticas por risk (§34–35).
- [ ] Roteamento puro (§31, §86): **AC-CONF-01, AC-CONF-02, AC-CONF-03 como testes de tabela.**
- [ ] Auto-approval com audit completo (§87: confidence, threshold, evidence, policy, versões de agente, timestamp).
- [ ] Serializer YAML determinístico (chaves ordenadas, 1 atom/arquivo, `domain/capability/kind/`) + export Git com escritor único no worker.
- [ ] CLI `semantic compile` validando o canonical-repo de forma independente (§59).
- [ ] Versionamento canonical + supersession (**AC-CAN-01, AC-CAN-02**) (§71–72).

**Critério de saída:** candidate sintético com sinais → auto-approve ou routing para humano conforme política; atom canonical aparece comitado no `canonical-repo` e `semantic compile` passa; recalcular score não reescreve histórico.

---

## Fase 3 — Governança UI (tamanho G — M4)

**Objetivo:** jornada humana completa (§100), operável com candidates sintéticos — validação de UX não espera o discovery.

Entregáveis:

- [ ] Seed de candidates sintéticos realistas (fixtures da capability exemplo do PRD: Invoice/AR).
- [ ] Home dashboard (§107) + Inbox personalizada (§37) com priorização composta v1 (§84).
- [ ] Kanban de governança (§38) + Review Card (§39).
- [ ] Decision Room (§40): statement, explicação, confidence com breakdown, evidence, impacto, comments, votos, ações.
- [ ] Review actions (§41) + votos individuais auditáveis (§42) + resumo para o owner (§44).
- [ ] Decision authority (§43): aprovar/rejeitar/reclassificar/exceção — só com autoridade no domínio (**AC-GOV-01..05**).
- [ ] Evidence Viewer em 3 camadas (§46, UX2): tradução de negócio → resumo → fonte técnica (**AC-EVI-02, AC-EVI-03**).
- [ ] Notificações in-app (§73) via consumidores de eventos.
- [ ] Human Review como evidence (§24).

**Critério de saída:** jornada §100 ponta a ponta no navegador (reviewer vota → expert revisa → owner canonicaliza) com dados sintéticos; AC-GOV-01..05 verdes; decisão simultânea de dois owners gera 409 (§105).

---

## Fase 4 — Discovery via harness Claude Code (tamanho G — M2)

**Objetivo:** substituir os candidates sintéticos por discovery real na capability piloto.

Pré-requisito de negócio (decidir antes de iniciar): **seleção da capability piloto** (§110–112: 1 domínio, 1–3 capabilities, 100–500 atoms esperados, especialistas conhecidos) + **conjunto gold-standard de perguntas** (§82) criado junto com os especialistas.

Entregáveis:

- [ ] Porta `CodeAnalysisEngine` + runner subprocess (`claude -p --output-format stream-json --json-schema ...`), portando do `motor` do Praxis: resgate via `--resume`, `--disallowedTools` somente leitura, `--max-budget-usd`, `CLAUDE_CONFIG_DIR`, log `.jsonl`, timeout + kill-tree, detecção de limite de franquia (reagendar job) e falha de auth.
- [ ] Clone/worktree descartável por run; verificação git pós-run.
- [ ] Registro de auditoria por run: versão do CLI, modelo, effort, hash do prompt, `session_id`, caminho do `.jsonl`, custo USD.
- [ ] Prompts BSP (política do §90 + obrigação de evidence arquivo/linha/commit): Code Discovery Agent e Test Discovery Agent (§11).
- [ ] Verificação de evidence no kernel: arquivo existe e range válido no commit citado.
- [ ] Corroboration Agent (segundo passe sobre candidates) + sinais de agreement (§88, sem contar mesma fonte duas vezes).
- [ ] Dedup (§11): hash normalizado + embedding (via OpenRouter) → `Potential Duplicate`.
- [ ] Porta `LLMProvider` sobre OpenRouter (Opus) + tradução de evidence para linguagem de negócio (alimenta o Evidence Viewer).
- [ ] Idempotência por `(source, commit, agent_version)`.

**Critério de saída:** jornada automática §99 real — discovery na capability piloto gera 100+ candidates com evidence verificada; parte auto-aprovada por política, parte roteada para a Inbox da Fase 3; custo por run visível.

---

## Fase 5 — Conflitos e Questions (tamanho M — M5)

**Objetivo:** jornada de conflito (§101) e gestão de perguntas.

Entregáveis:

- [ ] Conflict Detection Agent + criação de `Conflict` para assertions incompatíveis — nunca auto-merge (**AC-CON-01, AC-CON-02**).
- [ ] Conflict Resolution Workspace (§48–50): comparação de evidence, votos, ações do owner (**AC-CON-03**).
- [ ] Question management (§51): responder, atribuir, converter resposta em rule.
- [ ] Decomposição de regras (§47) sugerida pelo Review Assistant (porta OpenRouter).
- [ ] Canonical reopening (§74): nova evidence contraditória → Conflict + Reevaluation Request + notificação do owner, sem alterar o canonical (**AC-CAN-03**).

**Critério de saída:** jornada §101 ponta a ponta; canonical desafiado reabre por processo, nunca por overwrite.

---

## Fase 6 — Consumo do conhecimento (tamanho M — M6)

**Objetivo:** navegar, buscar, medir impacto e projetar o conhecimento canônico.

Entregáveis:

- [ ] Knowledge Explorer (§52): hierarquia Domain → Capability → Concepts/Rules/Decisions/Processes.
- [ ] Busca (§53): FTS + semântica (pgvector) + todos os filtros.
- [ ] Graph como projeção (§54): `atom_relations` + CTEs; Impact Analysis (§55); centralidade via NetworkX em job periódico alimentando a priorização (§56, §84).
- [ ] Context Builder (§61–62) + Agent Context Safety (§63: CANONICAL/OBSERVED/UNRESOLVED/UNKNOWN) (**AC-CTX-01..03**).
- [ ] Projeções (§64): BDD/Gherkin (§65), Decision Table view editável (§66), State Machine view (§67), Markdown docs.

**Critério de saída:** context package canonical-only gerado < 10s (§122); impact analysis responde "o que é afetado?"; Scenario vira Gherkin.

---

## Fase 7 — Métricas e calibração (tamanho P–M — M7)

**Objetivo:** fechar o Definition of Done e calibrar thresholds com uso real. (Os dados já existem desde a Fase 1 — aqui são dashboards + eval.)

Entregáveis:

- [ ] Semantic Coverage (§75) + Confidence Distribution (§76) + Capability/Audit dashboards (§108–109).
- [ ] KPIs (§77–81, §131): Human Review Cost, Automation Rate, False Auto-Approval Rate, Override Rate.
- [ ] Eval de Semantic Reconstruction Accuracy com o gold-standard da Fase 4 (§82): agente recebe só o IR canonical, respostas classificadas (Correct/Partial/Incorrect/Unknown-OK/Hallucinated).
- [ ] Rodada de calibração: ajustar fórmula de confidence (nova versão) e thresholds com base em override/false-approval.

**Critério de saída:** Definition of Done do MVP (§124, itens 1–18) integralmente verificável; targets do §132 medidos (mesmo que ainda não atingidos — são hipóteses a recalibrar).

---

## Transversais (valem para todas as fases)

- **Testes dos ACs primeiro**: cada AC do PRD (§125–130) vira teste automatizado na fase em que nasce; nenhuma fase fecha com AC da sua alçada vermelho.
- **Audit por construção**: nenhuma mutação fora dos serviços de domínio que emitem eventos.
- **Idioma**: UI e conteúdo gerado em pt-BR; IDs e schema do IR em inglês (como no PRD).
- **Segurança**: harness só em worktree descartável; secrets fora do repo; canonical-repo com push restrito ao worker.

## Dependências e pendências de decisão

| Pendência | Necessária até | Quem decide |
|---|---|---|
| Capability piloto + repositórios legados de origem | Início da Fase 4 | Negócio + especialistas |
| Gold-standard de perguntas da capability piloto | Início da Fase 4 | Especialistas de domínio |
| Conta(s) Claude para o harness (assinatura vs API key) e budget por run | Início da Fase 4 | Administrador |
| Chave OpenRouter | Início da Fase 4 | Administrador |
| Reviewers reais (3–10, §110) para uso piloto | Fase 5+ | Negócio |

Fases 0–3 não dependem de nenhuma pendência externa — a implementação pode começar imediatamente pela Fase 0.
