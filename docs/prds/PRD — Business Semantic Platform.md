# PRD — Business Semantic Platform
## MVP para extração, validação, governança e publicação de conhecimento semântico de sistemas legados

**Status:** Draft para implementação de MVP  
**Versão:** 1.0  
**Objetivo:** Construir uma plataforma operacional capaz de transformar conhecimento implícito de sistemas legados complexos em conhecimento semântico explícito, verificável, rastreável, governado e reutilizável.

---

# 1. Visão do Produto

A Business Semantic Platform é uma plataforma para reconstrução semântica de sistemas legados.

Seu objetivo não é documentar código.

Seu objetivo é transformar comportamento legado em um modelo confiável do negócio.

A plataforma deverá ser capaz de:

1. analisar fontes legadas;
2. descobrir conceitos, regras, decisões, invariantes, processos, estados e exceções;
3. registrar evidências;
4. calcular nível de confiança;
5. detectar ambiguidades, conflitos e lacunas;
6. decidir automaticamente quando o conhecimento possui confiança suficiente;
7. encaminhar para humanos apenas os casos que realmente precisam de julgamento;
8. permitir revisão colaborativa e decisão por especialistas;
9. publicar conhecimento aprovado em uma base semântica canônica;
10. gerar projeções e contextos para agentes que futuramente reconstruirão o sistema.

O produto deverá otimizar dois recursos simultaneamente:

- capacidade computacional dos agentes;
- atenção humana especializada.

O segundo é mais escasso.

Portanto, um princípio central do produto será:

> Humanos não devem revisar tudo. Humanos devem revisar aquilo em que máquinas não possuem confiança suficiente para decidir.

---

# 2. Problema

ERPs e sistemas corporativos de grande porte acumulam conhecimento durante anos ou décadas.

Esse conhecimento fica distribuído em:

- código-fonte;
- banco de dados;
- stored procedures;
- testes;
- telas;
- APIs;
- integrações;
- workflows;
- relatórios;
- configurações;
- logs;
- documentação;
- manuais;
- tickets;
- conhecimento tácito;
- comportamentos históricos.

Ao reconstruir o sistema em uma nova arquitetura, copiar o código ou converter documentação existente não garante preservação do negócio.

O sistema legado contém uma mistura de:

- regras legítimas;
- comportamentos observados;
- bugs;
- workarounds;
- customizações;
- regras históricas;
- exigências legais;
- decisões técnicas;
- regras específicas de clientes;
- comportamentos contraditórios.

O principal desafio é responder:

> Quais comportamentos representam efetivamente o negócio que deve ser preservado?

---

# 3. Objetivo do MVP

O MVP deverá permitir operar uma capability real de negócio ponta a ponta:

```text
Legacy Sources
      ↓
Automated Discovery
      ↓
Candidate Knowledge
      ↓
Confidence Evaluation
      ↓
Automatic Approval OR Human Governance
      ↓
Canonical Semantic Knowledge
      ↓
Graph / BDD / Context / Queries
```

O MVP será considerado bem-sucedido quando uma equipe de negócio conseguir utilizar a plataforma no trabalho cotidiano para transformar comportamento legado em conhecimento confiável sem precisar interagir diretamente com estruturas técnicas como YAML, JSON, CLI ou código-fonte.

---

# 4. North Star

A condição de longo prazo desejada é:

> Se tanto o sistema legado quanto sua futura implementação desaparecessem, um time competente deveria conseguir reconstruir um sistema semanticamente compatível utilizando apenas o conhecimento canônico armazenado na plataforma.

O MVP não precisa atingir essa condição integralmente, mas sua arquitetura deverá ser compatível com ela.

---

# 5. Hipótese Principal

A hipótese principal do produto é:

> Conhecimento extraído automaticamente de sistemas legados pode ser promovido de forma segura para uma base semântica confiável desde que possua evidência rastreável, validação estrutural, mecanismos de corroboração, cálculo de confiança e governança humana seletiva para situações de baixa confiança ou alto risco.

---

# 6. Princípios de Produto

## P1 — Semântica acima de implementação

O código legado é evidência.

O código legado não é automaticamente a regra de negócio.

---

## P2 — Machine first, human when necessary

A plataforma deverá buscar resolver automaticamente o maior número possível de situações.

A interação humana deverá ser utilizada quando:

- a confiança estiver abaixo do threshold;
- existirem conflitos;
- existirem ambiguidades;
- existirem evidências contraditórias;
- existir impacto relevante;
- política de governança exigir aprovação humana.

---

## P3 — Default confidence threshold

O threshold padrão para decisão automática será:

```text
90%
```

Esse valor deverá ser configurável.

Configurações possíveis:

```text
Global
Domain
Capability
Knowledge Atom Type
Risk Level
```

Exemplo:

```text
Global: 90%

Finance:
  95%

UI behavior:
  85%

Fiscal rules:
  100% human approval required
```

---

## P4 — Confidence não significa verdade

Confidence representa o nível de suporte disponível para uma afirmação.

Não deve ser interpretado como probabilidade matemática absoluta de a regra estar correta.

O score deverá ser explicável.

---

## P5 — Toda afirmação precisa de evidência

Nenhuma regra descoberta automaticamente pode existir sem evidência associada.

---

## P6 — Unknown é um resultado válido

O sistema deve preferir declarar:

```text
UNKNOWN
```

ou:

```text
NEEDS HUMAN DECISION
```

a inventar uma resposta.

---

## P7 — Conflitos são conhecimento

Conflitos nunca deverão ser removidos ou escondidos automaticamente.

---

## P8 — O canonical knowledge é protegido

Agentes podem:

- descobrir;
- sugerir;
- correlacionar;
- corroborar;
- apontar conflitos.

Mas a promoção para canonical deverá respeitar políticas explícitas.

---

## P9 — Human experience não expõe implementação desnecessária

Usuários de negócio não devem precisar compreender:

- YAML;
- repositórios;
- AST;
- embeddings;
- graph databases;
- ferramentas de build.

Esses detalhes poderão ser acessíveis sob demanda, mas nunca deverão ser a experiência principal.

---

## P10 — Tudo precisa ser auditável

Qualquer conhecimento deverá responder:

- quem descobriu;
- de onde veio;
- quando surgiu;
- quem revisou;
- quem aprovou;
- qual evidência existia;
- qual score existia;
- qual regra substituiu outra.

---

# 7. Personas

O MVP deverá suportar cinco papéis.

---

# 7.1 Viewer

Pode:

- pesquisar conhecimento;
- navegar em concepts;
- visualizar regras;
- visualizar decisões;
- visualizar evidências;
- consultar histórico.

Não pode modificar conhecimento.

---

# 7.2 Reviewer

Pode:

- avaliar candidates;
- comentar;
- votar;
- solicitar mais evidência;
- indicar conflito;
- sugerir alteração;
- sinalizar exceção.

---

# 7.3 Domain Expert

Possui conhecimento reconhecido sobre determinado domínio.

Pode:

- realizar todas as ações de Reviewer;
- receber prioridade em reviews daquele domínio;
- possuir peso informacional maior;
- resolver questions;
- sugerir canonicalização.

---

# 7.4 Decision Owner

Possui autoridade para decisão final em determinado domínio ou capability.

Pode:

- aprovar;
- rejeitar;
- definir interpretação;
- resolver conflitos;
- promover knowledge para canonical.

---

# 7.5 Administrator

Pode:

- configurar thresholds;
- configurar políticas;
- definir domains;
- atribuir owners;
- gerenciar usuários;
- configurar agentes;
- administrar fontes;
- definir integrações.

---

# 8. Modelo de Autoridade

Voting e authority deverão ser conceitos separados.

O sistema não deverá tomar decisão apenas pela contagem de votos.

Exemplo:

```text
5 reviewers confirmam
1 Tax Domain Owner rejeita
```

Isso não significa automaticamente aprovação.

A decisão deverá respeitar:

```text
Policy
+
Domain Authority
+
Confidence
+
Risk
```

---

# 9. Escopo Funcional do MVP

O MVP será composto pelos seguintes módulos:

1. Source Registry
2. Discovery Engine
3. Semantic Repository
4. Confidence Engine
5. Semantic Governance Workspace
6. Conflict Resolution Workspace
7. Evidence Viewer
8. Knowledge Explorer
9. Semantic Graph
10. Semantic Compiler
11. Context Builder
12. Projection Engine
13. Governance & Audit
14. Notifications
15. Semantic Metrics

---

# 10. Source Registry

Responsável por registrar as fontes que podem originar conhecimento.

Tipos iniciais:

```text
source_code
automated_test
documentation
database_schema
api
configuration
runtime_trace
manual
ticket
human_input
```

Cada Source deverá possuir:

```yaml
id:
type:
name:
location:
repository:
branch:
commit:
version:
domain:
metadata:
```

O MVP não precisa integrar automaticamente com todos os tipos.

Deverá suportar arquitetura extensível.

---

# 11. Discovery Engine

Responsável por analisar fontes e produzir Candidate Knowledge.

O Discovery Engine poderá utilizar múltiplos agentes especializados.

Exemplos:

```text
Code Discovery Agent
Test Discovery Agent
Documentation Discovery Agent
Database Discovery Agent
Corroboration Agent
Conflict Detection Agent
Duplicate Detection Agent
```

---

# 12. Output do Discovery Engine

O output nunca será diretamente canonical.

O pipeline produz:

```text
Candidate Knowledge Atoms
Evidence
Questions
Potential Conflicts
Potential Duplicates
Relations
Confidence Signals
```

---

# 13. Business Semantic IR

O núcleo do produto será o Business Semantic Intermediate Representation.

Tipos iniciais obrigatórios:

```text
Concept
Rule
Decision
Invariant
State
Transition
Event
Process
Scenario
Exception
Conflict
Question
Evidence
Capability
```

---

# 14. Common Knowledge Atom Envelope

Todos os Knowledge Atoms deverão utilizar um envelope comum.

```yaml
id:

kind:

title:

description:

domain:

capability:

status:

classification:

confidence:

risk:

scope:

effective:

evidence:

relations:

created_at:

created_by:

updated_at:

version:
```

---

# 15. Knowledge Atom — Concept

Representa um conceito de negócio.

Exemplo:

```yaml
id: FIN.AR.CONCEPT.INVOICE

kind: concept

title: Invoice

description: >
  Financial obligation issued to a customer.

domain: finance

capability: accounts-receivable
```

---

# 16. Knowledge Atom — Rule

Representa uma afirmação normativa.

Exemplo:

```yaml
id: FIN.AR.RULE.0012

kind: rule

title: Cancelled invoice cannot receive payment

statement: >
  Payments must not be applied to invoices
  whose status is cancelled.

classification:
  intended_behavior
```

---

# 17. Knowledge Atom — Decision

Representa uma decisão baseada em inputs.

```yaml
id: FIN.AR.DECISION.0011

kind: decision

inputs:
  - customer.risk_level
  - invoice.amount

output:
  approval_required

logic:
  type: decision_table
```

---

# 18. Knowledge Atom — Invariant

Representa propriedade que deve permanecer verdadeira.

```yaml
id: FIN.AR.INVARIANT.0004

kind: invariant

statement: >
  Invoice remaining balance must never
  become negative.
```

---

# 19. Knowledge Atom — State

Representa estado relevante.

Exemplo:

```text
Draft
Issued
Paid
Cancelled
Expired
```

---

# 20. Knowledge Atom — Transition

Representa mudança válida de estado.

```yaml
id: FIN.AR.TRANSITION.001

from: issued

to: cancelled

trigger:
  cancel_invoice

conditions:
  - FIN.AR.RULE.0012
```

---

# 21. Knowledge Atom — Scenario

Representa um exemplo concreto.

```yaml
id: FIN.AR.SCENARIO.0091

given:
  invoice.status: cancelled

when:
  apply_payment: true

then:
  result: rejected
```

---

# 22. Knowledge Atom — Exception

Representa exceção a uma regra.

```yaml
id: FIN.AR.EXCEPTION.0011

applies_to:
  FIN.AR.RULE.0032

condition:
  customer.type == GOVERNMENT
```

---

# 23. Evidence

Toda afirmação semântica automática deverá possuir Evidence.

Tipos:

```text
SOURCE_CODE
TEST
DOCUMENT
DATABASE
RUNTIME
API
UI
CONFIGURATION
HUMAN_REVIEW
DOMAIN_EXPERT
EXTERNAL_RULE
```

Exemplo:

```yaml
id: EVIDENCE.09182

type: SOURCE_CODE

source:
  repository: legacy-erp
  commit: abc123

location:
  file: InvoiceService.java
  start_line: 221
  end_line: 249
```

---

# 24. Human Review também é Evidence

Quando um especialista revisar uma regra, a decisão humana deverá ser registrada como evidência.

Exemplo:

```yaml
type: HUMAN_REVIEW

reviewer:
  role: TAX_DOMAIN_EXPERT

decision:
  CONFIRM_WITH_EXCEPTION
```

---

# 25. Classification

Conhecimento deverá poder ser classificado como:

```text
OBSERVED_BEHAVIOR
INTENDED_BEHAVIOR
MANDATED_BEHAVIOR
LEGACY_QUIRK
KNOWN_BUG
DEPRECATED_BEHAVIOR
UNKNOWN
```

---

# 26. Knowledge Lifecycle

Estados principais:

```text
DISCOVERED
CANDIDATE
CORROBORATING
READY_FOR_EVALUATION
AUTO_APPROVED
NEEDS_HUMAN_REVIEW
IN_REVIEW
DECISION_PENDING
CANONICAL
REJECTED
SUPERSEDED
```

Estados especiais:

```text
CONFLICTED
UNKNOWN
LEGACY_BUG
```

---

# 27. Confidence Engine

O Confidence Engine será responsável por calcular confidence.

O valor deverá estar entre:

```text
0.00 – 1.00
```

ou visualmente:

```text
0% – 100%
```

O cálculo deverá ser explicável.

---

# 28. Confidence Signals

O MVP deverá considerar pelo menos:

```text
number_of_independent_evidence
evidence_type_diversity
test_support
runtime_support
documentation_support
human_support
source_consistency
conflict_presence
duplicate_agreement
agent_agreement
rule_complexity
inference_distance
```

---

# 29. Evidence Independence

Duas evidências que derivam da mesma origem não deverão receber peso equivalente a duas evidências independentes.

Exemplo:

```text
Production Code
Unit Test mocking Production Code
```

podem não ser completamente independentes.

O Confidence Engine deverá permitir modelar esse fato progressivamente.

No MVP, uma heurística simples será suficiente.

---

# 30. Confidence Explainability

O usuário deverá conseguir visualizar:

```text
Confidence: 93%
```

e entender:

```text
+ Source code support
+ Automated test support
+ Documentation support
+ Agreement between 2 agents
- No runtime evidence
```

Nunca mostrar apenas um número sem justificativa.

---

# 31. Confidence Threshold

Default:

```text
90%
```

Comportamento padrão:

```text
confidence >= 90%
AND no conflict
AND policy allows auto approval
→ AUTO_APPROVED
```

Caso contrário:

```text
→ NEEDS_HUMAN_REVIEW
```

---

# 32. Threshold Configuration

Permitir:

```text
Global threshold
Domain threshold
Capability threshold
Atom type threshold
Risk threshold
```

Precedência:

```text
Risk/Policy
    >
Capability
    >
Domain
    >
Global
```

---

# 33. Mandatory Human Review Policy

Alguns tipos de conhecimento poderão exigir revisão humana independentemente de confidence.

Exemplo:

```text
Tax rule
Security policy
Financial accounting rule
Regulatory behavior
```

Configuração:

```yaml
human_review_required: true
```

---

# 34. Risk Classification

Todo candidate deverá poder receber:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

Risk poderá influenciar:

- threshold;
- número de reviewers;
- exigência de owner;
- auto approval.

---

# 35. Exemplo de Política

```text
LOW:
threshold = 85%

MEDIUM:
threshold = 90%

HIGH:
threshold = 95%

CRITICAL:
human approval required
```

O sistema deverá permitir customização.

---

# 36. Semantic Governance Workspace

O Semantic Governance Workspace será um dos núcleos do MVP.

Não será uma funcionalidade auxiliar.

Seu objetivo é:

> direcionar atenção humana apenas para decisões semanticamente relevantes.

---

# 37. Human Review Inbox

Ao entrar no sistema, cada usuário deverá visualizar uma Inbox personalizada.

Exemplo:

```text
7 regras aguardando sua revisão

2 conflitos no domínio Fiscal

3 questions relacionadas a Accounts Receivable

1 regra canonical possui nova evidência contraditória
```

A ordenação deverá considerar:

```text
Risk
Confidence
Domain relevance
Graph impact
Age
Decision urgency
```

---

# 38. Kanban de Governança

Visualização disponível:

```text
Needs Review
In Discussion
Needs Evidence
Needs Decision
Approved
Rejected
```

Kanban será utilizado como ferramenta de workflow.

Não será a única interface.

---

# 39. Review Card

Um card deverá mostrar apenas informação suficiente para triagem.

Exemplo:

```text
Cancelled invoice cannot receive payment

Finance / Accounts Receivable

Confidence: 82%
Risk: Medium

3 supporting evidence
1 conflicting evidence

Assigned:
Finance Reviewers
```

---

# 40. Decision Room

Abrir um card leva à Decision Room.

A Decision Room deverá possuir:

```text
Semantic statement
Plain-language explanation
Confidence
Evidence
Contradictory evidence
Related concepts
Related rules
Impact
Comments
Votes
Agent explanation
Decision actions
```

---

# 41. Review Actions

Reviewer poderá selecionar:

```text
CONFIRM
REJECT
CONFIRM_WITH_EXCEPTION
OBSERVED_ONLY
LEGACY_BUG
NEEDS_MORE_EVIDENCE
NEEDS_SPECIALIST
NOT_MY_DOMAIN
```

---

# 42. Voting

Votos serão armazenados individualmente.

Cada voto deverá registrar:

```text
Reviewer
Role
Domain expertise
Decision
Comment
Timestamp
```

Voting nunca será equivalente automaticamente a approval.

---

# 43. Decision Authority

Decision Owner poderá:

```text
Approve as canonical
Reject
Split rule
Merge rule
Add exception
Reclassify
Request more evidence
Resolve conflict
Mark known bug
```

---

# 44. Senior Decision

Quando existir votação, o Decision Owner deverá visualizar resumo.

Exemplo:

```text
7 reviewers

5 CONFIRM
1 CONFIRM_WITH_EXCEPTION
1 NEEDS_MORE_EVIDENCE

Domain Experts:
2 confirm
1 confirm with exception

Agent recommendation:
CONFIRM_WITH_EXCEPTION
```

A decisão final continuará pertencendo ao owner quando exigido por política.

---

# 45. Agent Facilitator

A Decision Room deverá possuir um agente assistente.

Funções:

```text
Explain why this rule was inferred
Summarize evidence
Find contradictory evidence
Explain impact
Suggest rule decomposition
Suggest exceptions
Summarize discussion
Generate decision summary
```

O agente nunca decidirá pelo owner quando human approval for obrigatório.

---

# 46. Evidence Viewer

O Evidence Viewer deverá apresentar primeiro uma tradução semanticamente acessível.

Exemplo:

```text
Evidence: Automated Test

A test verifies that applying a payment
to a cancelled invoice must fail.
```

Botão:

```text
View technical source
```

Então apresentar:

```text
Repository
File
Lines
Commit
Code excerpt
```

---

# 47. Knowledge Decomposition

Usuários poderão solicitar:

```text
Split this rule
```

Agent poderá sugerir decomposição.

Exemplo:

```text
Original:
Cancelled invoice cannot receive financial operations.

Suggested:

R1 Cancelled invoice cannot receive payment.
R2 Cancelled invoice may receive refund.
R3 Cancelled invoice may receive credit note.
```

---

# 48. Conflict Resolution Workspace

Quando evidências incompatíveis forem encontradas, criar Conflict.

Exemplo:

```text
Code:
Cancellation allowed before shipment.

Test:
Cancellation allowed before invoicing.

Manual:
Cancellation allowed until payment.
```

O sistema não deverá escolher automaticamente.

---

# 49. Conflict View

Mostrar:

```text
Topic
Competing assertions
Evidence for each
Confidence
Affected rules
Affected processes
Affected scenarios
Human votes
Comments
```

---

# 50. Conflict Resolution Actions

Decision Owner poderá:

```text
Select assertion A
Select assertion B
Create new interpretation
Split by scope
Split by time
Mark legacy bug
Mark unresolved
Request more evidence
```

---

# 51. Question Management

Questions deverão ser exibidas como itens próprios.

Exemplo:

```text
Can an invoice be cancelled after
fiscal authorization?
```

Usuários poderão:

- responder;
- comentar;
- atribuir especialista;
- relacionar evidence;
- converter resposta em rule.

---

# 52. Knowledge Explorer

O Knowledge Explorer será a experiência para navegar no conhecimento já estabelecido.

Hierarquia inicial:

```text
Domain
  → Capability
    → Concepts
    → Rules
    → Decisions
    → Processes
```

Exemplo:

```text
Finance
  Accounts Receivable
    Invoice
      Creation
      Payment
      Cancellation
      Collection
```

---

# 53. Search

Suportar:

```text
Full-text search
Semantic search
Filter by domain
Filter by capability
Filter by status
Filter by confidence
Filter by type
Filter by owner
Filter by risk
```

---

# 54. Semantic Graph

Graph será uma projeção da base semântica.

Não será source of truth.

Nodes poderão incluir:

```text
Concept
Rule
Decision
Process
State
Event
Scenario
Exception
Evidence
Capability
```

Edges:

```text
DEPENDS_ON
AFFECTS
USED_BY
GOVERNS
TRIGGERS
PRODUCES
CONSUMES
EVIDENCED_BY
EXEMPLIFIED_BY
CONTRADICTS
SUPERSEDES
```

---

# 55. Impact Analysis

Usuário deverá selecionar um atom e perguntar:

```text
What is affected if this changes?
```

Resposta:

```text
Direct impact
Transitive impact
Processes
Rules
Scenarios
Capabilities
```

---

# 56. Graph Centrality

A plataforma poderá utilizar importância estrutural do graph para ajudar a priorizar review.

Uma regra utilizada por dezenas de processos deverá possuir prioridade maior que uma regra isolada.

No MVP, heurísticas simples são suficientes.

---

# 57. Canonical Repository

Persistência canônica deverá utilizar formato textual versionável.

Sugestão:

```text
YAML + Git
```

Entretanto usuários de negócio nunca precisarão acessar YAML.

Arquitetura:

```text
Friendly UI
    ↓
Application API
    ↓
Semantic Domain Model
    ↓
Canonical Serializer
    ↓
YAML / Git
```

---

# 58. Discovery Space vs Canonical Space

O produto deverá manter separação lógica entre:

```text
Discovery Space
```

e:

```text
Canonical Space
```

Discovery Space pode conter:

- duplicatas;
- candidates;
- conflitos;
- perguntas;
- inferências.

Canonical Space deverá conter conhecimento aprovado.

---

# 59. Semantic Compiler

Responsável por:

```text
Schema validation
Reference validation
ID validation
Relation validation
Graph generation
Projection generation
Metrics generation
Consistency checks
```

Comando conceitual:

```text
semantic compile
```

---

# 60. Semantic Linter

Além da validação estrutural, criar semantic linter.

Detectar:

```text
Rule without evidence
Rule without scope
Broken references
Circular relations
Duplicate IDs
Invalid transition
Conflicting canonical rules
Orphan atoms
Missing capability
```

---

# 61. Context Builder

O Context Builder produzirá pacotes semânticos para agentes.

Input:

```text
Capability
Task
Concept
Rule
```

Exemplo:

```text
Implement invoice cancellation
```

Output:

```text
Context Package
```

---

# 62. Context Package

Deverá conter:

```text
Capability description
Relevant concepts
Canonical rules
Decisions
Invariants
States
Transitions
Processes
Exceptions
Scenarios
Known conflicts
Open questions
Evidence summaries
```

Por padrão, apenas canonical knowledge deverá ser utilizado.

Candidates poderão ser incluídos explicitamente.

---

# 63. Agent Context Safety

Context package deverá diferenciar:

```text
CANONICAL
OBSERVED
UNRESOLVED
UNKNOWN
```

para evitar que agentes tratem todo conteúdo como regra oficial.

---

# 64. Projection Engine

O MVP deverá suportar pelo menos:

```text
BDD / Gherkin
Decision Tables
Markdown Documentation
Agent Context
```

DMN e BPMN formais poderão ser evoluções posteriores.

---

# 65. BDD Projection

Scenario deverá poder gerar Gherkin.

Exemplo:

```gherkin
Scenario: Reject payment for cancelled invoice

  Given an invoice is cancelled

  When a payment is applied

  Then the payment must be rejected
```

---

# 66. Decision Table View

Decision deverá possuir uma interface tabular amigável.

Exemplo:

```text
Customer | Amount | Risk | Approval
Regular  | < 50k  | Low  | No
Regular  | >=50k  | Low  | Manager
Regular  | Any    | High | Director
Gov      | Any    | Any  | No
```

Usuário deverá poder revisar e editar visualmente.

---

# 67. State Machine View

States e Transitions deverão possuir representação gráfica.

Exemplo:

```text
Draft → Issued → Paid
          ↓
       Cancelled
```

Selecionar uma transition deverá mostrar condições.

---

# 68. Process View

Processes deverão possuir representação visual simples.

Não é necessário implementar BPMN completo no MVP.

Fluxos básicos deverão suportar:

```text
Step
Decision
Transition
Event
Condition
```

---

# 69. Governance & Audit

Toda alteração deverá gerar audit event.

Exemplo:

```text
RULE-102 created by Discovery Agent
RULE-102 confidence changed 78% → 91%
RULE-102 reviewed by Ana
RULE-102 approved by Finance Owner
RULE-102 became CANONICAL
```

---

# 70. Audit Requirements

Registrar:

```text
Actor
Action
Timestamp
Previous value
New value
Reason
Evidence
Related decision
```

---

# 71. Canonical Versioning

Cada canonical atom deverá possuir version.

Exemplo:

```text
FIN.AR.RULE.0012

v1
v2
v3
```

Histórico nunca deverá ser destruído.

---

# 72. Supersession

Quando uma regra mudar:

```text
RULE-A v1
```

deverá ser marcada como superseded.

Nova regra:

```text
RULE-A v2
```

deverá referenciar a anterior.

---

# 73. Notifications

Notificar usuários quando:

```text
Review assigned
Comment mentions user
Decision needs owner
New conflicting evidence found
Canonical rule reopened
Question assigned
Threshold/policy causes review
```

---

# 74. Canonical Reopening

Se nova evidência contradizer uma regra canonical:

Não alterar a regra automaticamente.

Criar:

```text
Conflict
```

e:

```text
Reevaluation Request
```

Notificar owner.

---

# 75. Semantic Coverage

Dashboard deverá exibir:

```text
Total atoms
Canonical atoms
Candidate atoms
Auto-approved atoms
Human-reviewed atoms
Conflicts
Questions
Rules with evidence
Rules with multiple independent evidence
Rules without scenarios
Rules without owner
```

---

# 76. Confidence Distribution

Dashboard:

```text
0–50%
50–70%
70–90%
90–95%
95–100%
```

Também mostrar:

```text
Percentage auto-approved
Percentage requiring human review
```

---

# 77. Human Attention Metrics

Métricas essenciais:

```text
Items sent to human review
Review hours
Average review time
Average decision time
Rules reviewed per expert
Percentage approved unchanged
Percentage modified
Percentage rejected
```

---

# 78. Human Review Cost

Criar métrica:

```text
Human Review Cost
```

Exemplos:

```text
Minutes per candidate
Hours per capability
Hours per 1,000 rules
```

Essa métrica deverá ser tratada como KPI central.

---

# 79. Automation Rate

Criar:

```text
Automation Rate
```

Fórmula:

```text
items resolved without human review
-----------------------------------
total evaluated items
```

O objetivo não será maximizar esse número cegamente.

Deverá ser equilibrado com qualidade.

---

# 80. False Auto-Approval Rate

Métrica crítica.

Definição:

```text
Auto-approved rules later corrected or rejected
------------------------------------------------
Total auto-approved rules
```

Essa deverá ser minimizada.

---

# 81. Human Override Rate

Métrica:

```text
Automatically suggested decisions
overridden by humans
```

Útil para calibrar confidence.

---

# 82. Semantic Reconstruction Accuracy

Criar conjunto de perguntas gold-standard por capability.

Agent recebe apenas canonical IR.

Classificação:

```text
Correct
Partially Correct
Incorrect
Unknown Correctly Identified
Hallucinated
```

---

# 83. Hallucination Safety

Métrica crítica:

```text
Unsupported assertions produced by agents
```

Objetivo:

```text
próximo de zero
```

---

# 84. Review Prioritization

A fila de review deverá utilizar score composto.

Exemplo conceitual:

```text
Review Priority =
    Risk
  + Business Impact
  + Graph Centrality
  + Conflict Severity
  + Confidence Gap
  + Age
```

---

# 85. Exemplo de Prioridade

Regra A:

```text
Confidence 88%
Low impact
No conflict
```

Regra B:

```text
Confidence 92%
Critical fiscal rule
3 conflicting evidence
used by 18 processes
```

Regra B deverá aparecer primeiro apesar de possuir confidence maior.

---

# 86. Automatic Approval Rules

Automatic approval poderá ocorrer quando:

```text
confidence >= configured threshold
AND no conflict
AND no mandatory human policy
AND no critical risk
AND semantic validation passes
```

---

# 87. Automatic Approval Audit

Auto approval deverá registrar:

```text
Confidence
Threshold
Evidence
Policy
Agent versions
Timestamp
```

---

# 88. Agent Agreement

Opcionalmente, o sistema poderá utilizar múltiplos agentes.

Exemplo:

```text
Agent A: rule detected
Agent B: confirms
Agent C: confirms
```

Agent agreement poderá aumentar confidence.

Mas agentes não deverão ser considerados evidências independentes quando utilizarem exatamente a mesma fonte.

---

# 89. Agent Architecture

Interfaces conceituais:

```text
DiscoveryAgent
CorroborationAgent
ConflictAgent
ExplanationAgent
ReviewAssistant
ContextAgent
```

Provider abstrato:

```text
LLMProvider
```

para permitir Codex, Claude ou outros modelos.

---

# 90. Agent Prompt Policy

Todos os agentes deverão seguir:

```text
Never create unsupported business facts.

Always distinguish observed behavior
from intended behavior.

Always attach evidence.

Create Question when uncertain.

Create Conflict when evidence disagrees.

Do not alter canonical knowledge directly.

Prefer small composable rules.

Never hide uncertainty.
```

---

# 91. Backend Suggested Architecture

Sugestão para MVP:

```text
Web Application
        ↓
Application API
        ↓
Domain Services
        ↓
Semantic Repository
        ↓
Canonical Store
```

Serviços principais:

```text
Discovery Service
Knowledge Service
Review Service
Confidence Service
Graph Service
Projection Service
Context Service
Audit Service
Notification Service
```

---

# 92. Technology Recommendations

Estas decisões são sugestões iniciais.

## Backend

```text
Python
FastAPI
Pydantic
```

## Frontend

```text
React / Next.js
```

## Operational Database

```text
PostgreSQL
```

## Canonical Artifacts

```text
YAML + Git
```

## Graph MVP

```text
NetworkX
```

ou:

```text
PostgreSQL relations
```

Migrar para graph DB somente se necessário.

## Background Jobs

```text
Celery / Dramatiq / equivalent
```

Não é necessário introduzir infraestrutura complexa prematuramente.

---

# 93. Operational Database vs Canonical Repository

PostgreSQL poderá armazenar:

```text
Users
Assignments
Comments
Votes
Notifications
Sessions
Workflow states
Cached graph data
```

Canonical Business Semantic IR deverá continuar exportável e versionável independentemente da aplicação.

---

# 94. API — Knowledge

Endpoints conceituais:

```text
GET    /knowledge
GET    /knowledge/{id}
POST   /knowledge/candidates
PATCH  /knowledge/{id}
GET    /knowledge/{id}/history
GET    /knowledge/{id}/evidence
GET    /knowledge/{id}/impact
```

---

# 95. API — Review

```text
GET  /reviews/inbox
GET  /reviews/{id}
POST /reviews/{id}/vote
POST /reviews/{id}/comment
POST /reviews/{id}/request-evidence
POST /reviews/{id}/decision
```

---

# 96. API — Conflicts

```text
GET  /conflicts
GET  /conflicts/{id}
POST /conflicts/{id}/resolve
```

---

# 97. API — Search

```text
GET /search
GET /graph
GET /context
```

---

# 98. Events

Arquitetura deverá estar preparada para emitir eventos.

Exemplos:

```text
CandidateDiscovered
EvidenceAdded
ConfidenceChanged
HumanReviewRequested
VoteSubmitted
DecisionMade
KnowledgeCanonicalized
ConflictDetected
CanonicalKnowledgeChallenged
```

---

# 99. MVP User Journey — Automatic Path

```text
Agent discovers Rule
        ↓
Evidence attached
        ↓
Corroboration
        ↓
Confidence = 94%
        ↓
No conflict
        ↓
Policy allows auto-approval
        ↓
AUTO_APPROVED
        ↓
CANONICAL
```

Nenhum humano é interrompido.

---

# 100. MVP User Journey — Human Path

```text
Agent discovers Rule
        ↓
Confidence = 73%
        ↓
Needs Human Review
        ↓
Reviewer receives Inbox item
        ↓
Reviews evidence
        ↓
Votes CONFIRM_WITH_EXCEPTION
        ↓
Agent suggests decomposition
        ↓
Domain Expert reviews
        ↓
Decision Owner approves
        ↓
CANONICAL
```

---

# 101. MVP User Journey — Conflict

```text
Agent discovers Rule A
Agent discovers Rule B
        ↓
Conflict detected
        ↓
Human Review
        ↓
Evidence comparison
        ↓
Expert discussion
        ↓
Decision Owner determines:
Rule varies by scope
        ↓
Create Rule A + scope
Create Rule B + scope
        ↓
CANONICAL
```

---

# 102. Authentication

MVP deverá possuir autenticação.

Pode inicialmente utilizar:

```text
Email/password
```

ou provider pronto.

Não implementar identidade corporativa complexa inicialmente, mas deixar extensível para SSO.

---

# 103. Authorization

RBAC obrigatório.

Permissões deverão considerar:

```text
Role
Domain
Capability
```

Exemplo:

```text
Ana:
Domain Expert
Finance
```

não implica authority em:

```text
Manufacturing
```

---

# 104. Multi-user Collaboration

Múltiplos usuários poderão:

```text
Review
Comment
Vote
Observe
```

simultaneamente.

Decisões deverão evitar overwrite silencioso.

---

# 105. Concurrency

Utilizar optimistic locking ou equivalente para decisões sensíveis.

Se dois owners tentarem decidir simultaneamente:

```text
detect conflict
```

e exigir refresh.

---

# 106. UX Principles

## UX1

Business language first.

## UX2

Progressive disclosure.

Primeiro mostrar:

```text
Business meaning
```

Depois:

```text
Evidence summary
```

Por último:

```text
Technical detail
```

## UX3

Uncertainty visible.

## UX4

Never force humans to read raw source unnecessarily.

## UX5

Every decision must answer:

```text
What am I deciding?
Why am I seeing this?
What evidence exists?
What happens if I approve?
```

---

# 107. Home Dashboard

Mostrar:

```text
My Review Queue
Pending Decisions
Open Conflicts
Open Questions
Recent Knowledge Changes
Coverage by Capability
```

---

# 108. Capability Dashboard

Para cada capability:

```text
Semantic coverage
Canonical rules
Candidates
Conflicts
Questions
Confidence distribution
Human review workload
Recent changes
```

---

# 109. Audit Dashboard

Para administradores e owners:

```text
Auto-approved rules
Human-approved rules
Reopened rules
Rejected rules
Overrides
Threshold performance
```

---

# 110. MVP Initial Scope

Para validar o produto de forma realista, selecionar:

```text
1 business domain
1–3 capabilities
```

Com volume suficiente para gerar:

```text
100–500 candidate atoms
```

e participação de:

```text
3–10 human reviewers
```

---

# 111. Ideal Capability Characteristics

Selecionar áreas que possuam:

```text
Business complexity
Tests
Code
Exceptions
State changes
Decision logic
Known subject matter experts
```

Evitar capability excessivamente trivial.

---

# 112. Recommended Initial Capabilities

Exemplos:

```text
Invoice Cancellation
Payment Allocation
Credit Limit Validation
```

---

# 113. MVP Milestone 1 — Semantic Foundation

Entregáveis:

```text
Knowledge Atom schemas
Canonical repository
Semantic compiler
Validation
Basic API
Basic persistence
```

---

# 114. MVP Milestone 2 — Discovery

Entregáveis:

```text
Source registry
Code discovery agent
Test discovery agent
Evidence extraction
Candidate creation
```

---

# 115. MVP Milestone 3 — Confidence

Entregáveis:

```text
Confidence engine
90% default threshold
Configurable thresholds
Risk
Auto approval
Human review routing
```

---

# 116. MVP Milestone 4 — Governance UI

Entregáveis:

```text
Login
Inbox
Kanban
Review Card
Decision Room
Evidence Viewer
Comments
Voting
Decision Owner approval
```

---

# 117. MVP Milestone 5 — Conflict Management

Entregáveis:

```text
Conflict detection
Conflict UI
Question management
Rule decomposition
```

---

# 118. MVP Milestone 6 — Knowledge Consumption

Entregáveis:

```text
Knowledge Explorer
Search
Graph
Impact analysis
Context Builder
BDD projection
Decision tables
```

---

# 119. MVP Milestone 7 — Metrics & Calibration

Entregáveis:

```text
Semantic coverage
Human review cost
Automation rate
Override rate
False auto-approval rate
Confidence calibration
```

---

# 120. Out of Scope — MVP

Não implementar inicialmente:

```text
Full BPMN engine
Full DMN runtime
OWL reasoning
Formal theorem proving
Automatic ERP generation
Data migration
Full legacy runtime replay
Multi-tenant SaaS billing
Advanced enterprise SSO
Mobile apps
Complex graph database infrastructure
Automatic regulatory interpretation
```

---

# 121. Non-Functional Requirements

## Auditability

100% das decisões devem ser rastreáveis.

## Explainability

Confidence e decisões automáticas deverão ser explicáveis.

## Recoverability

Canonical knowledge deverá ser versionado.

## Extensibility

Novos Knowledge Atom Types deverão ser adicionáveis.

## Provider Independence

LLM providers deverão ser substituíveis.

## Security

RBAC e domain authorization obrigatórios.

---

# 122. Performance Targets

Para MVP:

```text
Search < 2 seconds
Review page < 2 seconds
Graph neighborhood < 3 seconds
Context generation < 10 seconds excluding LLM processing
```

Não priorizar hiperescala prematuramente.

---

# 123. Data Integrity

O sistema deverá impedir:

```text
Broken references
Duplicate canonical IDs
Missing evidence on automated candidates
Invalid state transitions
Unauthorized canonical approval
Silent canonical overwrite
```

---

# 124. Definition of Done — MVP

MVP será considerado completo quando:

1. agentes conseguirem analisar fontes legadas;
2. candidates forem criados automaticamente;
3. evidence for preservada;
4. confidence for calculada;
5. threshold padrão de 90% estiver funcionando;
6. threshold puder ser configurado;
7. candidates acima do threshold puderem ser aprovados automaticamente por política;
8. candidates abaixo do threshold forem encaminhados para humanos;
9. humanos utilizarem interface amigável;
10. múltiplos humanos puderem votar;
11. Decision Owner puder tomar decisão final;
12. conflitos puderem ser resolvidos;
13. canonical knowledge for produzido;
14. graph for construído;
15. context packages puderem ser produzidos;
16. BDD puder ser gerado;
17. semantic coverage puder ser visualizada;
18. toda decisão for auditável.

---

# 125. Acceptance Criteria — Confidence Routing

## AC-CONF-01

Dado:

```text
confidence = 94%
threshold = 90%
no conflicts
no mandatory review
```

o sistema deverá:

```text
auto approve
```

---

## AC-CONF-02

Dado:

```text
confidence = 89%
threshold = 90%
```

o sistema deverá:

```text
route to human review
```

---

## AC-CONF-03

Dado:

```text
confidence = 99%
risk = critical
human_review_required = true
```

o sistema deverá:

```text
route to human review
```

---

# 126. Acceptance Criteria — Governance

## AC-GOV-01

Reviewer pode votar.

## AC-GOV-02

Reviewer não pode canonicalizar sem authority.

## AC-GOV-03

Decision Owner pode canonicalizar.

## AC-GOV-04

Todos os votos permanecem auditáveis.

## AC-GOV-05

Decisão final não apaga votos divergentes.

---

# 127. Acceptance Criteria — Evidence

## AC-EVI-01

Candidate automático sem evidence deverá ser rejeitado.

## AC-EVI-02

Evidence deverá permitir visualização amigável.

## AC-EVI-03

Usuário poderá abrir evidência técnica original.

---

# 128. Acceptance Criteria — Conflict

## AC-CON-01

Assertions contraditórias não poderão ser auto-merged.

## AC-CON-02

Conflict deverá gerar review item.

## AC-CON-03

Decision Owner deverá poder resolver conflict.

---

# 129. Acceptance Criteria — Canonical Knowledge

## AC-CAN-01

Canonical knowledge deverá ser versionado.

## AC-CAN-02

Alteração posterior deverá manter histórico.

## AC-CAN-03

Nova evidência contraditória não deverá alterar canonical automaticamente.

---

# 130. Acceptance Criteria — Context

## AC-CTX-01

Usuário seleciona capability.

Sistema gera Context Package.

## AC-CTX-02

Context Package deverá conter apenas canonical por padrão.

## AC-CTX-03

Open Questions e Conflicts deverão ser claramente identificados.

---

# 131. Primary Product KPIs

Os principais KPIs serão:

```text
Semantic Reconstruction Accuracy
False Auto-Approval Rate
Human Review Cost
Automation Rate
Human Override Rate
Conflict Resolution Time
Semantic Coverage
```

---

# 132. Product Success Criteria

Após uso real, o MVP deverá demonstrar:

```text
Alta precisão semântica
Baixa alucinação
Automação significativa
Redução de esforço humano
Boa rastreabilidade
Boa capacidade de reconstrução
```

Um exemplo inicial de target:

```text
> 90% semantic reconstruction accuracy

< 2% false auto-approval

> 60% automation rate

< 5 min median human review time
```

Esses números serão hipóteses iniciais e deverão ser recalibrados após uso real.

---

# 133. Critério Filosófico de Qualidade

O sistema deverá sempre preferir:

```text
Correctness
    >
Coverage
```

```text
Traceability
    >
Convenience
```

```text
Explicit Uncertainty
    >
Confident Hallucination
```

```text
Human Attention Optimization
    >
Human Review of Everything
```

---

# 134. Visão Arquitetural Final do MVP

```text
                         LEGACY SOURCES
                               │
                               ▼
                    ┌─────────────────────┐
                    │  DISCOVERY AGENTS   │
                    └──────────┬──────────┘
                               │
                               ▼
                   ┌───────────────────────┐
                   │   DISCOVERY SPACE     │
                   │                       │
                   │ Candidates            │
                   │ Evidence              │
                   │ Questions             │
                   │ Conflicts             │
                   └───────────┬───────────┘
                               │
                               ▼
                     ┌───────────────────┐
                     │ CONFIDENCE ENGINE │
                     └─────────┬─────────┘
                               │
                    ┌──────────┴─────────────┐
                    │                        │
             confidence >= policy      confidence < policy
                    │                        │
                    ▼                        ▼
              AUTO APPROVAL        HUMAN GOVERNANCE
                    │                        │
                    │              ┌─────────┴─────────┐
                    │              │                   │
                    │              ▼                   ▼
                    │           Review              Voting
                    │              │                   │
                    │              └─────────┬─────────┘
                    │                        ▼
                    │                 Expert Decision
                    │                        │
                    └─────────────┬──────────┘
                                  ▼
                      ╔══════════════════════╗
                      ║ CANONICAL SEMANTIC   ║
                      ║      KNOWLEDGE       ║
                      ╚══════════╤═══════════╝
                                 │
             ┌───────────────────┼───────────────────┐
             │                   │                   │
             ▼                   ▼                   ▼
       SEMANTIC GRAPH      PROJECTION ENGINE    CONTEXT BUILDER
             │                   │                   │
             ▼                   ▼                   ▼
       Impact Analysis      BDD / Tables      Coding Agents
```

---

# 135. Visão de Longo Prazo

O MVP deverá deixar base arquitetural para futuros recursos como:

```text
Semantic Diff
Automated Conformance Testing
Property-Based Testing
DMN Generation
BPMN Generation
Legacy Behavior Replay
Architecture-independent Certification
Semantic Change Impact
Business Rule Versioning
Regulatory Rule Packs
Automated New-System Validation
Implementation Agents
Semantic Coverage Maps
Multi-system Semantic Comparison
```

---

# 136. Resultado Esperado

Ao final do MVP, a organização deverá possuir uma plataforma que transforme:

```text
Legacy behavior
```

em:

```text
Explicit semantic knowledge
```

que passa por:

```text
Automated discovery
Automated corroboration
Confidence evaluation
Selective human governance
Canonical publication
```

O produto não deverá exigir que humanos revisem tudo.

O produto deverá identificar onde a máquina possui confiança suficiente e onde o conhecimento humano realmente agrega valor.

O objetivo central do MVP será, portanto:

> Construir uma linha de produção confiável de conhecimento semântico, na qual agentes executam trabalho em escala e humanos concentram sua atenção apenas nas decisões que realmente exigem julgamento.