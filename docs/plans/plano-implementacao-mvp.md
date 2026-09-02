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

## Fase 0 — Fundação (tamanho P) ✅ concluída em 2026-09-01

**Objetivo:** repositório operável com CI, banco, auth e esqueleto dos dois apps.

Entregáveis:

- [x] Monorepo: `backend/` (Python 3.12+, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, Procrastinate, ruff, pytest), `frontend/` (Next.js + TypeScript, pnpm), `canonical-repo/` (git dedicado, commit inicial), `docs/`.
- [x] Docker Compose: `db` (Postgres 16 + pgvector), `api` (:8000), `worker`, `web` (:3001 — a 3000 do host estava ocupada por Grafana local).
- [x] CI GitHub Actions (lint + testes com Postgres de serviço + migração em banco efêmero + build do frontend).
- [x] Migração inicial (`15f27daa52d6`) + auth e-mail/senha (argon2 via pwdlib) + JWT; bootstrap `python -m app.create_admin`.
- [x] RBAC: papéis do §7 com bindings `(user, role, domain?, capability?)` (§103), hierarquia de papéis e escopo que não vaza entre domains; dependency `require(role)`.
- [x] API admin mínima: users, domains, capabilities, role-bindings (validação capability↔domain).

**Critério de saída verificado:** login + `/auth/me` com binding escopado funcionando via containers; 16/16 testes verdes (unitários + integração contra Postgres); ruff limpo; `docker compose up -d` sobe os 4 serviços e o worker permanece ativo. (CI verde no GitHub pendente apenas de push para um remote.)

---

## Fase 1 — Kernel semântico (tamanho G — corresponde ao M1) ✅ concluída em 2026-09-02

**Objetivo:** o coração determinístico: IR, lifecycle, evidence, eventos, validação.

Entregáveis:

- [x] Schemas Pydantic do envelope (§14) + 13 kinds do IR (§13; Evidence é entidade própria) + `AtomTypeRegistry` com `register()` (novo kind sem migração — testado).
- [x] Tabelas: `sources`, `knowledge_atoms` (envelope em colunas + `body` JSONB + `lock_version`), `knowledge_atom_versions` (snapshot imutável a cada mutação), `evidence`, `evidence_links` (supports/contradicts), `atom_relations` (migração `26dc761a9876`).
- [x] State machine do lifecycle (§26) com todos os 14 estados mapeados; alvos com autoridade (CANONICAL/SUPERSEDED) e alvo exclusivo do sistema (AUTO_APPROVED).
- [x] Gate de evidence no serviço: candidate `origin=agent` sem evidence rejeitado (**AC-EVI-01** verde).
- [x] `domain_events` append-only na mesma transação; audit (§69–70) = eventos + snapshots via `/knowledge/{id}/history`; `CanonicalKnowledgeChallenged` em evidência contraditória sobre canonical (**AC-CAN-03** parcial, workflow completo na Fase 5).
- [x] Semantic Linter v1 com os 9 checks do §60, operando sobre coleção (reutilizável pelo `semantic compile` da Fase 2) e sobre o banco (`GET /knowledge/lint`).
- [x] API `/knowledge` (§94): list com todos os filtros do envelope, candidates, patch, status, evidence, relations, history, lint; Source Registry (§10) em `/sources`.
- [x] Optimistic locking em PATCH e mudança de status (`expected_lock_version` → 409, §105).

**Critério de saída verificado:** 52/52 testes verdes — lifecycle completo via API com audit (CandidateDiscovered → EvidenceAdded → StatusChanged/HumanReviewRequested → KnowledgeCanonicalized), reviewer barrado de canonicalizar (403) e owner aprovando (AC-GOV-02/03), transição inválida 409, lock desatualizado 409, cada violação do §60 acusada pelo linter; containers atualizados e smoke de `/knowledge` + `/knowledge/lint` ok.

---

## Fase 2 — Confidence, Policy e Canonical (tamanho M — antecipa o M3) ✅ concluída em 2026-09-02

**Objetivo:** roteamento automático explicável + publicação canônica versionada.

Entregáveis:

- [x] Confidence Engine v1 puro e versionado (`app/kernel/confidence.py`): os 12 sinais do §28 no breakdown (neutros declarados), independência por linhagem de origem (§29), penalidade por contradição; scores e sinais persistidos **append-only** (`confidence_scores` + `confidence_signals`).
- [x] Explicabilidade §30: breakdown por sinal com contribuição e explicação em `GET /knowledge/{id}/confidence`; formato "+/−" do PRD.
- [x] Policy Engine (`app/kernel/policy.py` + tabela `policies` + CRUD em `/admin/policies`): resolução campo a campo com precedência risk > capability > atom_kind > domain > global (§32) e **proveniência** de cada campo efetivo; default 90% (§31).
- [x] Roteamento puro §86 com os 5 checks (política obrigatória, risk crítico, conflito, validação semântica via linter, threshold): **AC-CONF-01/02/03 verdes como testes de tabela** e também via API.
- [x] Auto-approval com audit §87: evento `DecisionMade` com confidence, threshold+proveniência, evidence ids, engine_version, checks; caminho §99 completo (READY → AUTO_APPROVED → CANONICAL sem humano).
- [x] Serializer YAML determinístico (ordem fixa do envelope, 1 atom/arquivo em `domain/capability/kind/`) + exporter **reconciliador idempotente** com escritor único (queueing lock no Procrastinate); defer pós-commit em toda canonicalização.
- [x] CLI `semantic compile` (`uv run semantic compile`) validando o repo independente do banco (§59, §93): schema + registry + linter + métricas.
- [x] Versionamento canonical (`new-version`: v1→v2 no mesmo id, **AC-CAN-01/02**) + supersession por outro atom (SUPERSEDED + relação SUPERSEDES, §72); edição direta de canonical bloqueada (§123).

**Critério de saída verificado:** 81/81 testes verdes; smoke ao vivo nos containers — candidate com 4 evidências independentes → `score=0.93` → `AUTO_APPROVED` → `CANONICAL` → worker comitou `FINANCE.ACCOUNTS-RECEIVABLE.RULE.0001.yaml` no canonical-repo (commit "Export canonical: 1 atom(s) [auto-approval:…]") → `semantic compile` OK; reavaliação gera novo score sem apagar o anterior.

---

## Fase 3 — Governança UI (tamanho G — M4) ✅ concluída em 2026-09-02

**Objetivo:** jornada humana completa (§100), operável com candidates sintéticos — validação de UX não espera o discovery.

Entregáveis:

- [x] Seed sintético (`python -m app.seed_demo`): usuários ana/beto/carla@demo.bsp (reviewer/expert/owner em finance), capabilities do §112, 6 atoms em estados variados (canonical automático, conflito crítico com votos divergentes, pendente de decisão), source apontando para o praxis-autonomous.
- [x] Inbox personalizada (§37) com priorização composta v1 (§84) **explicável** (breakdown por termo: risk, conflito, confidence gap, idade, centralidade) + resumo de contagens; Kanban (§38) com as 6 colunas mapeadas ao lifecycle; Review Card (§39) mínimo para triagem.
- [x] Decision Room (§40) completa: statement em linguagem de negócio, confidence com breakdown ("por que este número?"), evidence, evidência contraditória destacada, relações/impacto, comments, votos, resumo do owner (§44) com recomendação heurística do sistema (que nunca decide, P8).
- [x] Review actions (§41, as 8) + votos individuais auditáveis (§42: reviewer, papel, expertise, decisão, comentário, timestamp; evento VoteSubmitted) + primeiro voto abre a discussão.
- [x] Decisão do owner (§43): APPROVE/REJECT/RECLASSIFY/MARK_KNOWN_BUG/REQUEST_EVIDENCE/ADD_EXCEPTION (cria atom exception ligado por applies_to); **AC-GOV-01..05 verdes**; split/merge ficam para a Fase 5.
- [x] Evidence Viewer em 3 camadas (§46/UX2): tradução de negócio primeiro, botão "Ver fonte técnica" (location + excerpt) — AC-EVI-02/03 na UI.
- [x] Notificações in-app (§73): roteamento p/ revisão, decisão aguardando owner, evidência contraditória em canonical, menção em comentário; badge no nav, marcar lida/todas.
- [x] Human Review como evidence (§24): votos assertivos viram evidence HUMAN_REVIEW/DOMAIN_EXPERT (supports; REJECT → contradicts) e a aprovação do owner também — **fechando o loop com o Confidence Engine** (teste: voto de expert sobe o score).
- [x] Frontend Next.js: telas Inbox, Kanban, Decision Room e Notificações; login redireciona à Inbox.

**Critério de saída verificado:** 92/92 testes verdes — jornada §100 completa via API (votos divergentes preservados após canonicalização, AC-GOV-04/05), dois owners simultâneos → 409 (§105); seed rodado nos containers e Inbox real da Carla priorizando corretamente (crítica com conflito 8.2 > alta 5.1 > decisão pendente 3.2); web em http://localhost:3001 com as 4 telas respondendo.

---

## Fase 4 — Discovery via harness Claude Code (tamanho G — M2) ✅ concluída em 2026-09-02

**Objetivo:** substituir os candidates sintéticos por discovery real na capability piloto.

Pré-requisitos resolvidos: capability piloto = praxis-autonomous; **gold-standard gerado** (23 perguntas verificadas, [docs/eval/praxis-gold.yaml](../eval/praxis-gold.yaml)).

Entregáveis:

- [x] Porta `CodeAnalysisEngine` (`app/engines/claude_code.py`): porte do `motor` do Praxis — stream-json, `--json-schema` com resgate via `--resume`, `--disallowedTools` somente leitura, `--max-budget-usd`, credencial ambiente, log `.jsonl` por run, timeout + kill-tree, detecção de limite de franquia (job reagenda em 30min) e falha de auth. Correção sobre o original: limite/auth só são avaliados em runs COM erro — um resultado bem-sucedido cujo conteúdo menciona "session limit"+"reset" (ex.: conhecimento extraído sobre a própria detecção do Praxis) dava falso positivo.
- [x] Workspace descartável (`git clone` efêmero por run) + verificação git pós-run (`workspace_clean` auditado).
- [x] Auditoria por run em `discovery_runs` + `/discovery/runs`: CLI, modelo, effort, hash do prompt, session_id, log `.jsonl`, custo US$, contadores.
- [x] Prompts BSP (§90) com evidence arquivo/linha OBRIGATÓRIA + schemas estruturados; Code e Test Discovery Agents (§11).
- [x] Verificação mecânica de evidence contra o commit: arquivo existe, range válido, e o **excerpt é extraído do arquivo real** (nunca do LLM). Candidate sem evidence válida é rejeitado.
- [x] Corroboration Agent (§88): segundo agente busca evidência independente (SUPPORTS/CONTRADICTS/NOT_FOUND); atoms sem votos voltam a CORROBORATING e re-roteiam; agent_agreement conta criadores distintos.
- [x] Dedup: hash normalizado exato (pula) + similaridade difflib ≥0.85 (`PotentialDuplicateDetected`, nunca merge — P7). Embedding ficou de fora: OpenRouter não oferece embeddings (verificado); pg_trgm/embeddings ficam para evolução.
- [x] Porta `LLMProvider` sobre OpenRouter (`anthropic/claude-opus-5`, verificado no catálogo) + endpoint de tradução de evidence.
- [x] Idempotência por `(source, commit, agent, prompt_hash)`; questions isentas do gate de evidence (P6 — pergunta não é afirmação).
- [x] Execução: CLI `python -m app.discovery_cli` no host + fila `discovery` (worker Docker restrito à `default`).
- [x] Engine de confidence v1→**v1.1**: linhagem de independência por ARQUIVO (source inteira colapsava tudo numa linhagem); histórico v1 preservado (append-only).

**Critério de saída verificado com 4 runs REAIS sobre o praxis-autonomous (commit 1c615ae, Opus effort high):**
- **102 candidates + 24 questions = 126 atoms**, com **342 evidências — e ZERO citações inválidas em todos os runs** (a verificação mecânica + ameaça de verificação no prompt funcionaram);
- custo total **US$ 8,20** (code 1: $1,89 · test: $1,07 · corroboration: $2,15 · code 2: $3,09), visível por run em `/discovery/runs`;
- corroboração adicionou 95 evidências de suporte + **6 contradições reais** — o atom contradito ("Quem faz o commit é sempre o orquestrador") saltou para o topo da Inbox (prioridade 9,3, §85);
- roteamento honesto: nenhum auto-approval — corpus só de código+teste atinge no máx. 0,78 (sem doc/runtime/humano não se chega a 90%) → tudo na Inbox da Fase 3, correctness > coverage (§133); a jornada automática §99 completa segue provada pelos testes e pelo smoke da Fase 2;
- qualidade das questions: o agente detectou, p.ex., que `perfil.go` existe no working tree mas não no commit clonado — e perguntou em vez de inventar (P6);
- 101/101 testes verdes (runner com harness falso: parsing, limite, auth, resgate `--resume`, ingestão, dedup, idempotência, corroboração).

---

## Fase 5 — Conflitos e Questions (tamanho M — M5) ✅ concluída em 2026-09-02

**Objetivo:** jornada de conflito (§101) e gestão de perguntas.

Entregáveis:

- [x] Conflito como atom (kind `conflict`, status CONFLICTED, estado próprio open/resolved/unresolved no body — P7: nunca removido). Criação automática: evidência contraditória abre conflito (1 aberto por atom) e move o atom a CONFLICTED — **canonical nunca muda sozinho**. Detecção por varredura (`POST /conflicts/detect`): evidências contraditórias + relações CONTRADICTS; **Conflict Detection Agent LLM** (porta OpenRouter) para contradições semânticas entre statements, com ids alucinados descartados. **AC-CON-01/02 verdes** (nunca auto-merge; conflito entra na Inbox).
- [x] Conflict Resolution Workspace (§48–50): Conflict View com lados, evidence e confidence de cada assertion + votos; resolução exclusiva do owner (**AC-CON-03**) com SELECT_ASSERTION, SPLIT_BY_SCOPE/TIME, NEW_INTERPRETATION, MARK_LEGACY_BUG, REQUEST_EVIDENCE, MARK_UNRESOLVED; lock otimista (§105) na resolução; resolução **recusa tocar canonical** (encaminha a new-version/supersede).
- [x] Question management (§51): listar/filtrar, responder (Domain Expert, §7.3), atribuir (notifica, §73), converter resposta em rule — a resposta vira evidence DOMAIN_EXPERT (§24) e a question aponta `converted_to` com relação PRODUCES.
- [x] Decomposição (§47): `suggest-decomposition` via Review Assistant (OpenRouter) — só sugere; `decompose` aplicado pelo owner (§43 Split rule): sub-regras SUPERSEDES a original, original REJECTED.
- [x] Canonical reopening (§74, **AC-CAN-03**): evidência contraditória em canonical → Conflict com `reevaluation: true` + notificação do owner + eventos, canonical intocado.
- [x] UI: páginas Conflitos (lista por estado), Conflict View (lados com evidência técnica sob demanda + painel de resolução do owner) e Questions (responder/atribuir/converter inline).

**Critério de saída verificado:** 109/109 testes verdes — jornada §101 completa por teste (conflito → split por escopo → duas regras com escopo → CANONICAL); canonical desafiado reabre por processo (conflito de reavaliação + notificação) e resolução que tentaria mudá-lo é recusada. Sobre os dados REAIS do Praxis: a varredura criou 1 conflito aberto para o invariant com as 6 contradições da corroboração ("Quem faz o commit é sempre o orquestrador"), visível em `/conflicts` e na UI.

---

## Fase 6 — Consumo do conhecimento (tamanho M — M6) ✅ concluída em 2026-09-02

**Objetivo:** navegar, buscar, medir impacto e projetar o conhecimento canônico.

Entregáveis:

- [x] Knowledge Explorer (§52): árvore Domain → Capability com contagens por kind/canonical (`/explorer`) + detalhe agrupado por kind; UI com navegação e projeções inline.
- [x] Busca (§53): full-text Postgres (coluna tsvector gerada + GIN, config portuguese) com ranking + fallback fuzzy por trigram (pg_trgm), com todos os filtros do envelope. *Busca por embedding adiada: o OpenRouter não oferece embeddings (verificado no catálogo); pgvector entra quando houver provedor de embedding.*
- [x] Graph como projeção (§54): `GET /graph` (vizinhança até N saltos) e Impact Analysis (§55) em `/knowledge/{id}/impact` com direção de propagação explícita por tipo de relação (direto + transitivo + agrupado por kind).
- [x] Centralidade (§56): NetworkX em job periódico do worker (30min) gravando `atoms.centrality` (grau normalizado 0..1 — heurística simples, como o próprio §56 pede) e alimentando a priorização da Inbox (§84), com fallback por contagem de relações.
- [x] Context Builder (§61–63): `GET /context?capability=…` em JSON e Markdown — **AC-CTX-01/02/03 verdes**: só canonical por padrão, candidates apenas explícitos rotulados OBSERVED, conflitos abertos UNRESOLVED e questions UNKNOWN sempre presentes, com safety note (§63).
- [x] Projeções (§64–68): BDD/Gherkin por scenario e feature por capability (§65), Decision Table (§66, renderizada na Decision Room; edição via PATCH do body), State Machine (§67), documentação Markdown (§64). UI: Explorer + Gherkin/tabela/impact na página do atom.

**Critério de saída verificado:** 118/118 testes verdes; context package real de `demand-pipeline` gerado em **26ms** (limite: 10s) e honesto — `canonical: 0` (nada do Praxis foi aprovado por humanos ainda), 1 conflito UNRESOLVED e 24 questions UNKNOWN rotulados; impact analysis com teste cobrindo cadeia processo→regra→cenário (direto + transitivo); scenario vira Gherkin (endpoint + UI); busca real "franquia esgotada" no domain praxis: 8 hits full-text.

---

## Fase 7 — Métricas e calibração (tamanho P–M — M7) ✅ concluída em 2026-09-02

**Objetivo:** fechar o Definition of Done e calibrar thresholds com uso real. (Os dados já existem desde a Fase 1 — aqui são dashboards + eval.)

Entregáveis:

- [x] Semantic Coverage (§75) — todos os 11 indicadores, incluindo rules com múltiplas evidências independentes (por linhagem) e rules sem owner; Coverage by Capability (§107); Confidence Distribution (§76) nos buckets do PRD; Audit dashboard (§109) com threshold performance (score no roteamento × desfecho — verificado por teste que abaixo de 90% nunca houve auto-approval).
- [x] KPIs (§77–81, §131) em `/metrics/attention`, todos derivados do event log (D4, sem instrumentação extra): sent-to-review, decisões de owner, latência mediana/média até decisão (wall-clock, rotulado), votos por reviewer, % aprovado sem/com alteração e rejeitado, Automation Rate, False Auto-Approval Rate (auto-aprovados depois desafiados/alterados/superseded), Human Override Rate (proxy explicável documentado).
- [x] Eval §82/§83 (`uv run python -m app.eval_cli run`): respondente recebe SÓ o Context Package (§63 aplicado), juiz classifica nas 5 categorias do PRD; relatório JSON persistido; testado com provider falso e executado DE VERDADE via OpenRouter/Opus.
- [x] Home Dashboard (§107) no frontend: tiles (fila, decisões, conflitos, automation rate, false auto-approval, latência), coverage por capability, distribuição de confidence, audit e mudanças recentes.
- [x] Calibração: a rodada deste ciclo foi o **engine v1→v1.1** (linhagem por arquivo, Fase 4) — recalibração de thresholds exige uso humano real; a infraestrutura (override rate, false auto-approval, threshold performance, políticas como dados) está pronta para a próxima rodada.

**Critério de saída verificado:** 125/125 testes verdes; eval REAL sobre o gold-standard do praxis-autonomous (23 perguntas):
- canonical-only (§82 estrito): **17,4%** estrito, 3/3 unknowns corretos, **0 alucinações** — baseline honesto: `canonical: 0` porque a governança humana ainda não aprovou nada; o agente disse "NÃO SEI" em vez de inventar (§83 atingido);
- com candidates OBSERVED (exploratório): **65,2% estrito / 69,6% com crédito parcial, 0 alucinações** — o conhecimento já extraído responde 2/3 do gold-standard; o delta 17→65% quantifica o valor na fila de revisão.

---

## Definition of Done do MVP (§124) — verificação final

| # | Critério | Evidência |
|---|---|---|
| 1 | Agentes analisam fontes legadas | 4 runs reais sobre o praxis-autonomous (Fase 4) |
| 2 | Candidates criados automaticamente | 102 candidates + 24 questions reais |
| 3 | Evidence preservada | 342 evidências verificadas contra o commit, zero inválidas |
| 4 | Confidence calculada | Engine v1.1, 12 sinais, breakdown explicável |
| 5 | Threshold 90% funcionando | AC-CONF-01/02 verdes + threshold performance no audit |
| 6 | Threshold configurável | Políticas como dados, precedência §32, AC-CONF-03 |
| 7 | Auto-approval por política | Smoke Fase 2 + atom auto-canonical exportado no Git |
| 8 | Abaixo do threshold → humanos | 102 candidates reais roteados para a Inbox |
| 9 | Interface amigável | 9 telas (login, dashboard, inbox, kanban, decision room, conflitos, questions, explorer, notificações) |
| 10 | Múltiplos votos | §42 com papel/expertise/timestamp; AC-GOV-01/04/05 |
| 11 | Owner decide | §43 completo; AC-GOV-02/03; §105 (409) |
| 12 | Conflitos resolvidos | §50 completo; jornada §101 testada; conflito real do Praxis aberto |
| 13 | Canonical produzido | Postgres + export YAML/Git determinístico + `semantic compile` |
| 14 | Graph construído | Relations + vizinhança + impact §55 + centralidade §56 |
| 15 | Context packages | §61–63, AC-CTX-01..03, 26ms |
| 16 | BDD gerado | §65 por scenario e por capability |
| 17 | Semantic coverage visível | §75/§107 no dashboard |
| 18 | Toda decisão auditável | Event log append-only = audit por construção (D4) |

**Targets §132 (hipóteses, medidos):** reconstruction accuracy 65,2% potencial (target >90% — exige aprovação humana do corpus + mais passes de discovery); false auto-approval 0 casos reais (medição ativa); automation rate real ainda não representativa (corpus aguarda revisão humana); alucinação **0** (target: próximo de zero ✓).

---

## Transversais (valem para todas as fases)

- **Testes dos ACs primeiro**: cada AC do PRD (§125–130) vira teste automatizado na fase em que nasce; nenhuma fase fecha com AC da sua alçada vermelho.
- **Audit por construção**: nenhuma mutação fora dos serviços de domínio que emitem eventos.
- **Idioma**: UI e conteúdo gerado em pt-BR; IDs e schema do IR em inglês (como no PRD).
- **Segurança**: harness só em worktree descartável; secrets fora do repo; canonical-repo com push restrito ao worker.

## Dependências e pendências de decisão

**Resolvidas (2026-09-01):**

- ~~Conta Claude para o harness~~ — o runner usa a **credencial ambiente** já configurada na máquina (`claude` logado no PATH), como o Praxis faz quando não há perfil gerenciado. Sem gestão de assinatura/API key pela plataforma; budget por run continua via `--max-budget-usd`.
- ~~Chave OpenRouter~~ — `.env` criado na raiz com `OPENROUTER_API_KEY` (ignorado pelo git; `.env.example` versionado). Preencher durante as primeiras fases.

**Resolvidas (2026-09-01, para o projeto de implementação):**

- ~~Capability piloto~~ — **o próprio `praxis-autonomous`** (`C:\Projetos\praxis-autonomous`): projeto pequeno, mapeável 100%, com código Go + testes + regras de negócio reais (pipeline de demandas, gates, franquia de motores). O projeto maior ("pra valer") será definido depois, no uso real.
- ~~Gold-standard de perguntas~~ — será **gerado pela IA** no início da Fase 4, sobre o comportamento do praxis-autonomous, e armazenado em `docs/eval/`. No projeto maior, será refeito com os especialistas de domínio.
- ~~Reviewers reais~~ — adiado para o projeto maior; o desenvolvimento usa **dados sintéticos** e testadores internos em todas as fases.

**Em aberto (apenas para o projeto "pra valer", pós-MVP técnico):** capability de negócio real + gold-standard com especialistas + reviewers nomeados.

Detalhamento das pendências em aberto:

### 1. Capability piloto + repositórios legados (§110–112)

A fatia do sistema legado onde o MVP será provado ponta a ponta. Critérios de seleção (§111): complexidade de negócio real (regras, exceções, mudanças de estado, lógica de decisão), existência de código E testes, e especialistas vivos e acessíveis. Evitar capability trivial (não prova valor) e escopo amplo demais (afoga os reviewers). Alvo: volume que gere 100–500 candidate atoms. Exemplos do PRD (§112): Cancelamento de Nota/Fatura, Alocação de Pagamento, Validação de Limite de Crédito. Entregar: nome do domínio + 1–3 capabilities, lista dos repositórios de origem (com acesso de leitura para clone) e commit/branch de referência.

### 2. Gold-standard de perguntas (§82–83)

Conjunto de 20–50 perguntas sobre a capability piloto com respostas corretas validadas pelos especialistas, escrito **antes** de rodar o discovery (para não ser contaminado pelo que a plataforma extrair). É a régua do KPI central (Semantic Reconstruction Accuracy) e do teste de alucinação: um agente recebe só o IR canonical e responde; cada resposta é classificada (Correct / Partially / Incorrect / Unknown-corretamente-identificado / Hallucinated). Incluir deliberadamente perguntas cuja resposta correta é "não definido no sistema" — para verificar que a plataforma responde UNKNOWN em vez de inventar (P6). Armazenar versionado em `docs/eval/`.

### 3. Reviewers reais (§7, §8, §110)

As 3–10 pessoas que usarão o workspace de governança no piloto, com papéis atribuídos: maioria **Reviewers**, 1–2 **Domain Experts** (peso maior, resolvem questions), **1 Decision Owner** nomeado por domínio/capability — sem owner, nada canonicaliza no caminho humano quando a política exigir aprovação (§8, AC-GOV-03) — e 1 **Administrator**. Definir também a expectativa de dedicação (ex.: ~30 min/dia durante o piloto) — o tempo deles alimenta o KPI Human Review Cost. Não bloqueia o desenvolvimento: a Fase 3 valida a UI com dados sintéticos e testadores internos; os reviewers reais entram quando candidates reais fluírem (fim da Fase 4 / Fase 5).
