# Proposta Arquitetural — Business Semantic Platform (MVP)

**Status:** Proposta para discussão
**Base:** PRD — Business Semantic Platform v1.0
**Data:** 2026-09-01

---

## 1. Leitura arquitetural do PRD

Antes das decisões, o diagnóstico. Apesar de listar 15 módulos, o PRD descreve essencialmente **uma máquina de estados com gates de governança**: Knowledge Atoms percorrem um ciclo de vida (`DISCOVERED → … → CANONICAL`), e cada transição é controlada por regras determinísticas (evidência obrigatória, confidence, política, autoridade). Tudo o mais — graph, projeções, métricas, context packages — é **projeção derivada** desse núcleo.

Os drivers arquiteturais reais (dos NFRs, §121–123) são:

1. **Auditabilidade 100%** — nenhuma mutação pode escapar do registro.
2. **Explicabilidade** — confidence e decisões automáticas nunca são caixa-preta.
3. **Integridade** — referências quebradas, canonical duplicado, aprovação sem autoridade e overwrite silencioso devem ser *impossíveis*, não apenas improváveis.
4. **Extensibilidade** — novos tipos de atom sem reescrever o sistema.
5. **Independência de provider LLM.**

E os *não-drivers*: escala (100–500 atoms, 3–10 reviewers), alta disponibilidade, multi-tenancy. O próprio PRD (§92, §120, §122) manda não introduzir infraestrutura complexa prematuramente.

Disso derivam as duas decisões que governam todas as outras.

---

## 2. Decisões estruturantes

### D1 — Monólito modular, um deploy + um worker

Um único backend FastAPI com módulos internos de fronteiras explícitas (mapeando os serviços do §91), mais um processo worker para jobs assíncronos. Nada de microserviços, nada de message broker externo no MVP.

**Por quê:** na escala do MVP, microserviços só adicionariam latência de desenvolvimento e modos de falha distribuídos — exatamente o que os KPIs do produto (precisão, rastreabilidade) não toleram. As fronteiras de módulo + eventos internos (D4) preservam o caminho de extração futura se algum módulo precisar escalar separadamente.

### D2 — Núcleo determinístico separado dos agentes LLM ("kernel semântico")

Esta é a decisão mais importante para robustez. O sistema se divide em duas zonas com contratos rígidos entre elas:

```text
┌────────────────────────────────────────────────────┐
│  ZONA PROBABILÍSTICA (agentes LLM)                 │
│  Discovery, Corroboration, Conflict Detection,     │
│  Explanation, Review Assistant                     │
│  → só podem PROPOR, via payloads estruturados      │
└──────────────────────┬─────────────────────────────┘
                       │ candidates + evidence (JSON validado)
                       ▼
┌────────────────────────────────────────────────────┐
│  KERNEL DETERMINÍSTICO (código puro, testável)     │
│  Schemas do IR · State machine do lifecycle        │
│  Confidence Engine · Policy Engine · Authority     │
│  Semantic Compiler/Linter · Serializer canônico    │
│  → única porta de escrita; rejeita o que violar    │
│    invariantes (ex.: candidate sem evidence)       │
└────────────────────────────────────────────────────┘
```

**Por quê:** todos os acceptance criteria do PRD (AC-CONF, AC-GOV, AC-EVI, AC-CON, AC-CAN) tornam-se testes unitários de funções puras, executáveis sem LLM. O agente pode alucinar à vontade — o kernel rejeita candidate sem evidência (AC-EVI-01), impede transição ilegal de estado e impede canonicalização sem autoridade. A confiabilidade do produto não depende do comportamento do modelo, e sim de código verificável. Isso também implementa P8 (canonical protegido) por construção, não por convenção de prompt.

### D3 — PostgreSQL como fonte da verdade; YAML+Git como projeção canônica determinística

O PRD sugere "YAML + Git" para o repositório canônico (§57) e ao mesmo tempo exige colaboração multiusuário, optimistic locking, busca, filtros e RBAC por domínio (§53, §103–105). Essas exigências são incompatíveis com Git como fonte primária de escrita.

**Proposta:** Postgres é o sistema de registro operacional E canônico. A cada evento `KnowledgeCanonicalized` (e a cada nova versão), um worker serializa o atom para YAML determinístico (chaves ordenadas, um arquivo por atom, diretórios por `domain/capability/kind`) e faz commit em um repositório Git dedicado (`canonical-repo`), com escritor único serializado.

**Por quê:** o §93 exige que o IR canônico seja "exportável e versionável independentemente da aplicação" — exportável, não que Git seja a origem. Esse desenho entrega: transações e locking no Postgres; recoverability e portabilidade no Git (o North Star §4 — reconstruir tudo só com o conhecimento canônico — é satisfeito pelo repo Git); diffs legíveis por serialização determinística. O comando `semantic compile` valida o repo exportado de forma independente, servindo de verificação cruzada contra drift.

### D4 — Log de eventos append-only com padrão outbox (não event sourcing completo)

Toda mutação passa por um serviço de domínio que, **na mesma transação**, grava o novo estado e o(s) evento(s) de domínio (§98: `CandidateDiscovered`, `ConfidenceChanged`, `DecisionMade`, `KnowledgeCanonicalized`…) em uma tabela `domain_events` imutável.

Consumidores (no worker): auditoria, notificações, export Git, recálculo de confidence, refresh do graph, métricas.

**Por quê:**
- **Auditabilidade 100% por construção** — o audit trail (§69–70) *é* o event log; não existe caminho de escrita que não gere evento.
- **Métricas de graça** — todas as métricas dos §75–81 (automation rate, false auto-approval, override rate, review cost) viram consultas sobre eventos; o Milestone 7 deixa de ser um módulo e vira dashboards sobre dados que existem desde o dia 1.
- Event sourcing completo (estado reconstruído dos eventos) foi rejeitado: custo alto, e o requisito é trilha auditável, não replay.

### D5 — Atoms: envelope tipado em colunas + corpo por `kind` em JSONB + registry de schemas

```text
knowledge_atoms
  id, kind, title, domain, capability, status, classification,
  confidence, risk, scope, version, lock_version, created_by, …   ← colunas (índices, filtros)
  body JSONB                                                       ← campos específicos do kind
knowledge_atom_versions   ← snapshot imutável a cada versão (supersession §72)
```

Cada `kind` (Concept, Rule, Decision, Invariant, State, Transition, Scenario, Exception…) tem um schema Pydantic registrado num **AtomTypeRegistry**. Validação ocorre na escrita (API e agentes usam os mesmos schemas).

**Por quê:** o envelope comum do §14 vira colunas consultáveis (performance dos filtros do §53 sem Elasticsearch); novo tipo de atom = novo schema no registry, **sem migração de banco** (NFR de extensibilidade). `lock_version` implementa o optimistic locking do §105. Evidence, relations, conflicts, questions, votes, comments e policies são tabelas próprias relacionais — precisam de integridade referencial forte (§123).

### D6 — Confidence e Policy como funções puras, versionadas e explicáveis

- **Sinais** (§28) são persistidos como fatos (`confidence_signals`: tipo, valor, evidências de origem).
- **Score** = função determinística versionada sobre os sinais. Nenhum LLM calcula score. O resultado é gravado **com o breakdown** de contribuições (§30) e a versão da função — recalibrar a fórmula depois não reescreve a história.
- **Independência de evidência** (§29): heurística v1 — evidências são agrupadas por linhagem de origem (mesmo arquivo/commit/documento raiz); grupos repetidos têm retorno decrescente.
- **Políticas são dados, não código**: tabela `policies` com seletor de escopo (global/domain/capability/atom-type/risk), threshold, `human_review_required`, mínimo de reviewers, exigência de owner. Resolução segue a precedência do §32 (Risk/Policy > Capability > Domain > Global).
- **Roteamento** (§31, §86) = função pura `(candidate, score, conflitos, política) → AUTO_APPROVED | NEEDS_HUMAN_REVIEW` que retorna também a explicação, gravada no audit (§87). Recalculado por evento (`EvidenceAdded`, `ConflictDetected` → re-score → re-route).

**Por quê:** AC-CONF-01/02/03 viram testes de tabela; P4 (score explicável) é estrutural; calibração futura (§119) é troca de versão de função, com A/B possível sobre o event log.

### D7 — Graph e busca dentro do Postgres

- `atom_relations (from_id, to_id, edge_type)` com os edge types do §54; **impact analysis** (§55) via CTE recursiva; **centralidade** (§56) via job periódico com NetworkX, resultado cacheado em coluna (alimenta a priorização de review §84).
- **Busca**: full-text nativo (tsvector) + `pgvector` para busca semântica (embeddings dos títulos/statements). Um único banco.

**Por quê:** o PRD já aponta isso (§92: "NetworkX ou PostgreSQL relations; migrar para graph DB somente se necessário"; §120 exclui infra de graph complexa). Na escala de 500–5.000 atoms, CTEs respondem em milissegundos — os targets do §122 (graph < 3s) sobram. Graph é projeção (§54), então trocar o motor depois não toca o modelo.

### D8 — Jobs assíncronos com fila transacional no Postgres (Procrastinate)

Discovery, corroboration, re-score, export Git, notificações e snapshot de centralidade rodam no worker via **Procrastinate** (fila sobre Postgres, LISTEN/NOTIFY).

**Por quê:** o enqueue acontece **na mesma transação** do evento de domínio — commit = job garantido, rollback = job nenhum. Zero jobs perdidos/fantasma sem precisar de Redis/broker (menos uma peça stateful para operar). O PRD sugere "Celery/Dramatiq ou equivalente" (§92); se o time preferir Celery+Redis, a troca fica isolada atrás de uma interface fina de enqueue — mas perde-se a transacionalidade, que aqui vale muito.

### D9 — Agentes: pipeline com contratos estruturados e LLMProvider plugável

- Interfaces do §89 (`DiscoveryAgent`, `CorroborationAgent`, `ConflictAgent`, `ExplanationAgent`, `ReviewAssistant`, `ContextAgent`) como handlers de jobs.
- Porta `LLMProvider` com adapter inicial **Anthropic** (SDK oficial):
  - **Modelo default: `claude-opus-5`** com adaptive thinking — extração de regras de negócio de código legado é tarefa de raciocínio pesado; errar aqui custa atenção humana (o recurso mais escasso, §1).
  - **Structured outputs** (`output_config.format` / `messages.parse`): o agente devolve JSON que valida contra os próprios schemas Pydantic do IR — candidato malformado é impossível por construção, não por parsing defensivo.
  - **Batch API** para varreduras de discovery em massa (50% do custo; discovery não é sensível a latência).
  - **Prompt caching**: a política de prompt do §90 + o contexto da capability formam um prefixo estável cacheado; só o trecho de fonte varia por chamada.
- **Dedup** (§11): hash de conteúdo normalizado + similaridade de embedding → gera `Potential Duplicate`, nunca merge automático (P7).
- Idempotência: jobs de discovery são versionados por `(source, commit, agent_version)`; re-execução não duplica candidates.
- Gate final é sempre o kernel (D2): mesmo um agente mal-comportado não insere candidate sem evidence nem toca canonical.

### D10 — API, frontend e autorização

- **API**: FastAPI com os routers dos §94–97 (`/knowledge`, `/reviews`, `/conflicts`, `/search`, `/graph`, `/context`) + `/admin` (policies, domains, users). Optimistic locking exposto via `version` + `If-Match` (409 em conflito de decisão, §105).
- **Frontend**: Next.js + TypeScript. Três workspaces (Governança/Inbox+Kanban+Decision Room; Conflitos+Questions; Knowledge Explorer+dashboards). **Progressive disclosure dirigida pelo servidor**: a API entrega evidence já em três camadas (tradução de negócio → resumo → fonte técnica crua, §46/UX2), de modo que a regra "business language first" não dependa de disciplina de UI.
- **AuthN**: e-mail/senha (argon2) + sessão JWT; estrutura pronta para OIDC depois (§102).
- **AuthZ**: RBAC com *bindings escopados* — `(user, role, domain?, capability?)` (§103). Checagem de autoridade para canonicalizar/resolver conflito é função do kernel (mesma regra na API e nos serviços), atendendo AC-GOV-02/03 e "unauthorized canonical approval" (§123).

---

## 3. Visão geral

```text
                        ┌──────────────────────────────┐
                        │   Frontend (Next.js + TS)    │
                        │ Governança · Conflitos ·     │
                        │ Explorer · Dashboards        │
                        └──────────────┬───────────────┘
                                       │ REST/JSON
┌──────────────────────────────────────▼───────────────────────────────────┐
│                        Backend FastAPI (monólito modular)                │
│                                                                          │
│  api/            routers + RBAC + optimistic locking                     │
│  kernel/         IR schemas · lifecycle · confidence · policy ·          │
│                  authority · compiler/linter · serializer   (código puro)│
│  services/       knowledge · review · conflict · question · audit        │
│  agents/         discovery · corroboration · conflict · assistant       │
│  llm/            LLMProvider → AnthropicAdapter (opus-5, batch, cache)   │
│  projections/    graph · context builder · BDD · decision tables · md    │
│  persistence/    SQLAlchemy · outbox · fila (Procrastinate)              │
└───────┬──────────────────────────────────────────────────────┬───────────┘
        │ mesma transação: estado + domain_events + jobs       │
        ▼                                                      ▼
┌───────────────────────┐    worker (consumidores de eventos/jobs)
│ PostgreSQL (+pgvector)│    ├─ discovery/corroboration (LLM)
│  fonte da verdade     │    ├─ re-score → re-route
│  operacional+canônica │    ├─ export YAML → git commit (escritor único)
└───────────────────────┘    ├─ notificações · centralidade · métricas
                             ▼
                   ┌──────────────────┐
                   │ canonical-repo   │  YAML determinístico, 1 atom/arquivo
                   │ (Git)            │  validado por `semantic compile`
                   └──────────────────┘
```

Monorepo: `backend/` (Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, Procrastinate), `frontend/` (Next.js), `canonical-repo/` (Git separado ou submódulo), `docs/`. Docker Compose: `db`, `api`, `worker`, `web`.

---

## 4. Sequência de implementação

A ordem dos milestones do PRD é boa, com dois ajustes de eficiência:

1. **Kernel antes de agentes, UI cedo com dados sintéticos.** O Discovery (M2) só entra depois que o kernel (M1 + roteamento do M3) estiver estável, porque os agentes escrevem contra os contratos do kernel. Enquanto isso, a UI de governança (M4) é validada com candidates sintéticos/manuais — o risco de UX (reviewers adotarem a ferramenta) é tão alto quanto o risco técnico e não deve esperar a qualidade de extração.
2. **Métricas desde o dia 1 via event log** (D4). O M7 vira construção de dashboards, não instrumentação tardia — e o conjunto gold-standard do §82 deve ser criado já na seleção da capability piloto, não no fim.

| Fase | Conteúdo | Corresponde a |
|------|----------|---------------|
| 0 | Monorepo, Compose, CI, migrações, auth+RBAC básico | — |
| 1 | **Kernel**: schemas IR, registry, lifecycle, evidence, compiler/linter, eventos+outbox, API knowledge | M1 |
| 2 | **Confidence+Policy**: sinais, score explicável, políticas, roteamento (ACs como testes), export Git | M3 (antecipado) |
| 3 | **Governança**: Inbox, Kanban, Review Card, Decision Room, votos, decisão, audit — com candidates sintéticos | M4 |
| 4 | **Discovery**: Source Registry, Code/Test Discovery Agents, corroboration, dedup — na capability piloto real | M2 |
| 5 | **Conflitos e Questions**: detecção, workspace, decomposição de regras | M5 |
| 6 | **Consumo**: Explorer, busca (FTS+semântica), graph/impact, Context Builder, BDD, decision tables | M6 |
| 7 | **Calibração**: dashboards de métricas, gold-standard eval, ajuste de thresholds | M7 |

Ao fim da Fase 3 existe um produto operável ponta a ponta (com ingestão manual); as fases seguintes substituem o manual por automação e ampliam consumo.

---

## 5. Riscos principais e mitigações

| Risco | Mitigação arquitetural |
|-------|------------------------|
| Qualidade da extração LLM (alucinação, regra inventada) | Structured outputs + gate de evidência no kernel (AC-EVI-01) + `UNKNOWN`/`Question` como saídas de primeira classe (P6) + gold-standard eval desde a Fase 4 |
| Falsa precisão do confidence score | Fórmula v1 simples e monotônica, versionada, com breakdown sempre visível; calibração posterior via override rate sobre o event log |
| Drift entre Postgres e repo Git canônico | Escritor único serializado, serialização determinística, `semantic compile` como verificação independente no CI do canonical-repo |
| Escopo (15 módulos) esmagar o MVP | Kernel + governança são o produto; graph, projeções, métricas e context são projeções finas sobre os mesmos dados (D4/D7) — não módulos independentes |
| Reviewers não adotarem a ferramenta | UI de governança validada cedo com dados sintéticos (Fase 3); progressive disclosure no servidor; métrica de tempo de review desde o início |
| Custo de LLM em varreduras grandes | Batch API (−50%), prompt caching, discovery incremental por commit/fonte |

---

## 6. Stack (consolidado)

| Camada | Escolha | Observação |
|--------|---------|------------|
| Backend | Python 3.12+ · FastAPI · Pydantic v2 · SQLAlchemy 2 + Alembic | Conforme sugestão do PRD §92 |
| Banco | PostgreSQL 16 + pgvector | Único stateful store |
| Fila/jobs | Procrastinate (fila sobre Postgres) | Enqueue transacional; Celery+Redis como alternativa |
| Grafo | Tabela de relations + CTEs; NetworkX p/ centralidade | Graph DB só se provar necessário |
| Busca | Postgres FTS + pgvector | Sem Elasticsearch no MVP |
| LLM | SDK Anthropic · `claude-opus-5` · structured outputs · Batch API · prompt caching | Atrás da porta `LLMProvider` (NFR de independência) |
| Frontend | Next.js + TypeScript | Conforme PRD |
| Canonical | YAML determinístico + Git (projeção) | Postgres é a fonte da verdade |
| Auth | E-mail/senha + JWT; RBAC com bindings por domínio/capability | Extensível a OIDC/SSO |
| Deploy MVP | Docker Compose (db, api, worker, web) | Sem Kubernetes no MVP |
