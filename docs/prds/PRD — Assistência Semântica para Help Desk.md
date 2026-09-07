# PRD — Assistência Semântica para Help Desk
## Contexto seguro e orientado por pergunta para agentes de atendimento e analistas N1, N2 e N3

**Status:** Vertical slice implementado; automação de rollout/freshness ainda incremental
**Versão:** 1.1
**Produto base:** Business Semantic Platform (BSP)  
**Objetivo:** Transformar o conhecimento semântico reconstruído pelo BSP em contexto operacional, rastreável e mensurável para agentes de Help Desk que atendem usuários finais e apoiam analistas.

---

# 1. Resumo Executivo

O BSP já registra conhecimento de negócio como atoms tipados, com evidências, confiança,
classificação, risco, lifecycle, conflitos, questions e histórico.

Este PRD define a camada de consumo específica para Help Desk.

O objetivo não é esperar que todo conhecimento se torne perfeitamente canônico antes de ser
utilizado. O objetivo é utilizar o melhor conhecimento disponível, controlando o risco no momento
do consumo por meio de:

- recuperação orientada pela pergunta;
- resolução explícita de contexto e escopo;
- diferenciação entre conhecimento canônico, provisório, observado, conflitante e desconhecido;
- políticas distintas para resposta direta e apoio a analistas;
- referências rastreáveis aos atoms e evidências utilizados;
- detecção de conhecimento potencialmente obsoleto;
- feedback operacional mensurável.

O produto deverá fornecer contexto para dois modos principais:

1. **Help Desk Direct:** agente que responde diretamente ao usuário final;
2. **Help Desk Copilot:** agente que auxilia analistas N1, N2 e N3.

O BSP continuará sendo a fonte do conhecimento. O agente consumidor continuará responsável por
redigir a resposta conversacional, seguindo as instruções e restrições presentes no pacote.

---

# 2. Contexto e Problema

Sistemas legados concentram grande parte de suas regras operacionais no código-fonte, em mensagens,
validações de tela, SQL, parâmetros e comportamentos históricos.

Em muitos ambientes:

- não há documentação confiável;
- os testes são incompletos ou recentes;
- existem customizações por cliente, empresa ou filial;
- regras diferentes convivem em versões distintas;
- mensagens de erro não explicam a causa nem a solução;
- o atendimento depende de poucas pessoas experientes;
- o conhecimento produzido durante tickets não retorna para uma base reutilizável.

O gargalo de Help Desk não é apenas encontrar uma regra. É encontrar rapidamente a regra correta
para o contexto correto e convertê-la em uma orientação acionável.

O Context Package atual do BSP é organizado por capability. Ele é adequado como projeção geral,
mas não resolve integralmente o caso de Help Desk porque:

- não seleciona conhecimento com base na pergunta;
- não utiliza o campo `task` para recuperar ou priorizar atoms;
- pode gerar pacotes grandes demais;
- não resolve escopo de produto, versão, cliente, tela, permissão ou estado;
- não entrega todas as relações e informações de evidência disponíveis internamente;
- não possui contrato específico para resposta direta ou apoio técnico;
- não registra se o contexto fornecido resolveu o atendimento.

---

# 3. Decisão de Produto

O produto adotará a seguinte premissa:

> Ausência de validação humana não torna o conhecimento inutilizável. Ela altera a forma como o
> conhecimento pode ser consumido, afirmado, monitorado e corrigido.

A confiança será utilizada como sinal operacional, não como sinônimo de verdade.

O sistema não dependerá de uma divisão binária entre "aprovado" e "inutilizável". O consumo será
graduado conforme:

- lifecycle status;
- classificação;
- risco;
- significance;
- confiança;
- escopo;
- vigência;
- freshness;
- existência de conflitos;
- perfil de consumo.

O produto deverá preservar a diferença entre:

```text
O sistema faz isto.
```

e:

```text
O negócio determina que isto deve ser feito.
```

Código-fonte pode sustentar fortemente a primeira afirmação. Ele não prova sozinho a segunda.

---

# 4. Visão do Produto

Quando um usuário ou analista fizer uma pergunta, o BSP deverá produzir um pacote pequeno,
relevante, rastreável e adequado ao perfil de consumo.

Fluxo conceitual:

```text
Pergunta e contexto operacional
        ↓
Resolução de domain, capability e escopo
        ↓
Recuperação textual + semântica + relacional
        ↓
Filtros de segurança, lifecycle, risco e freshness
        ↓
Ranking e montagem sob orçamento de tokens
        ↓
Help Desk Context Package
        ↓
Agente responde, pergunta ou escala
        ↓
Resultado e feedback retornam ao BSP
```

---

# 5. Objetivos

O produto deverá:

1. recuperar conhecimento com base na pergunta e no contexto operacional;
2. reduzir respostas corretas aplicadas no escopo errado;
3. permitir uso pragmático de conhecimento provisório e observado;
4. oferecer políticas diferentes para usuário final e analistas;
5. transformar regras em orientação operacional;
6. preservar rastreabilidade até atom, versão, evidência e commit;
7. identificar conflitos, lacunas e necessidade de esclarecimento;
8. detectar conhecimento potencialmente obsoleto;
9. registrar quais conhecimentos foram utilizados em cada atendimento;
10. medir resolução, escalonamento, reabertura e correção;
11. criar um caminho seguro para transformar feedback em nova evidência;
12. melhorar continuamente a recuperação sem promover popularidade a verdade semântica.

---

# 6. Resultados Esperados

Para o usuário final:

- respostas mais rápidas e consistentes;
- instruções aplicáveis ao contexto informado;
- menos transferências desnecessárias;
- perguntas de clarificação mais relevantes;
- menor exposição a explicações técnicas internas.

Para N1:

- procedimentos objetivos;
- pré-condições e validações;
- mensagens relacionadas;
- perguntas que precisam ser feitas ao usuário;
- indicação clara de quando escalar.

Para N2 e N3:

- hipóteses ordenadas;
- evidências técnicas;
- arquivo, linhas, símbolo, mecanismo e commit;
- regras relacionadas;
- conflitos e lacunas conhecidas;
- indicação de possível obsolescência.

Para o produto:

- redução de tempo médio de atendimento;
- aumento de resolução no primeiro contato;
- visibilidade sobre perguntas ainda não respondíveis;
- aprendizado estruturado a partir de tickets reais;
- priorização de discovery com base na demanda operacional.

---

# 7. Fora de Escopo Inicial

Não faz parte da primeira entrega:

- substituir completamente o sistema de tickets;
- responder automaticamente todo tipo de solicitação;
- executar alterações no sistema legado;
- desbloquear usuários, alterar dados ou conceder permissões;
- transformar feedback positivo em canonical automaticamente;
- provar intenção de negócio usando apenas código-fonte;
- produzir BPMN ou DMN formal;
- treinar ou realizar fine-tuning de modelos;
- garantir semanticamente toda resposta gerada por um LLM;
- armazenar indiscriminadamente conversas contendo dados pessoais.

---

# 8. Personas

## 8.1 Usuário Final

Pessoa que utiliza o sistema legado e precisa concluir uma operação, entender uma mensagem ou saber
por que uma ação não está disponível.

Não deve receber:

- caminhos internos de repositórios;
- trechos de código;
- informações sobre vulnerabilidades;
- instruções para burlar validações ou permissões;
- terminologia de governança do BSP sem necessidade.

## 8.2 Agente de Atendimento Direto

Agente de IA que responde ao usuário final utilizando o perfil `helpdesk_direct`.

Deverá:

- responder apenas com o que o pacote sustenta;
- considerar escopo e vigência;
- pedir informações ausentes quando elas mudarem a resposta;
- não resolver silenciosamente conflitos;
- escalar quando a política determinar;
- registrar os atoms utilizados.

## 8.3 Analista N1

Responsável pelo primeiro diagnóstico e pela execução de procedimentos conhecidos.

Precisa de:

- procedimentos;
- perguntas de triagem;
- mensagens e causas prováveis;
- critérios de sucesso;
- critérios de escalonamento.

## 8.4 Analista N2

Responsável por investigação funcional e configuração.

Precisa também de:

- parâmetros;
- regras relacionadas;
- diferenças de escopo;
- decisões e transições;
- evidências técnicas resumidas.

## 8.5 Analista N3

Responsável por investigação profunda e correções técnicas.

Precisa também de:

- excerpts;
- arquivo, linhas, commit e símbolo;
- mecanismo da regra;
- histórico e confidence breakdown;
- grafo e impacto;
- indicação de fontes divergentes.

## 8.6 Gestor de Help Desk

Responsável por políticas de uso, qualidade, escalonamento e indicadores.

Deverá configurar:

- permissões de cada perfil;
- uso de provisórios;
- regras para risco crítico;
- orçamento de contexto;
- retenção de interações;
- rollout por capability.

---

# 9. Princípios de Produto

## HD-P1 — Melhor conhecimento disponível

Conhecimento útil não deverá ser ocultado apenas por não ser canonical. Seu uso deverá ser
condicionado e rastreado.

## HD-P2 — Escopo antes da resposta

Uma regra recuperada fora do seu escopo não será considerada suporte suficiente para uma resposta.

## HD-P3 — Resposta direta e investigação são produtos diferentes

O agente voltado ao usuário final receberá menos detalhes e uma política mais restritiva. O copiloto
de analistas receberá hipóteses, incertezas e evidências técnicas.

## HD-P4 — Evidência permanece acessível

Toda orientação deverá ser rastreável aos atoms utilizados. Analistas autorizados deverão conseguir
chegar às evidências originais.

## HD-P5 — Conflito não é consenso

Conhecimentos conflitantes nunca deverão ser fundidos silenciosamente em uma resposta única.

## HD-P6 — Feedback não é verdade automática

Sucesso operacional melhora utilidade e ranking. Correções podem produzir candidates. Nenhum dos
dois altera automaticamente uma regra canonical.

## HD-P7 — Último comportamento conhecido é informação útil

Conhecimento potencialmente antigo poderá ser utilizado quando permitido, desde que freshness e
versão sejam preservadas.

## HD-P8 — Segurança não depende apenas do prompt

Controle de acesso, remoção de dados sensíveis e filtragem de evidência serão realizados antes da
montagem do pacote.

## HD-P9 — O pacote não inventa a resposta

O Context Builder seleciona e organiza conhecimento. Ele não cria fatos ausentes.

## HD-P10 — Toda resposta precisa ser avaliável

Deverá ser possível saber quais atoms sustentaram uma resposta e qual foi o resultado operacional.

---

# 10. Escopo Funcional

O escopo será dividido em seis capacidades:

1. perfis de consumo;
2. resolução de contexto;
3. recuperação e ranking;
4. Help Desk Context Package;
5. knowledge freshness;
6. feedback e avaliação operacional.

---

# 11. Perfis de Consumo

## 11.1 `helpdesk_direct`

Destinado a agentes que respondem ao usuário final.

Regras padrão:

| Condição | Uso permitido |
|---|---|
| CANONICAL e vigente | Afirmar como comportamento aplicável |
| PROVISIONAL + OBSERVED_BEHAVIOR + não crítico + escopo compatível | Afirmar como comportamento atual, com rastreabilidade interna |
| PROVISIONAL + LEGACY_QUIRK ou KNOWN_BUG | Explicar comportamento/workaround sem apresentá-lo como política desejada |
| Candidate/OBSERVED abaixo do piso direto | Usar apenas para perguntar ou recomendar escalonamento |
| INTENDED/MANDATED sustentado apenas por código | Não afirmar como política oficial |
| CONFLICTED | Perguntar, apresentar limitação adequada ou escalar |
| UNKNOWN | Não inventar; coletar informação ou escalar |
| Risk CRITICAL | Não fornecer decisão irreversível sem regra específica de autorização |
| STALE | Utilizar apenas se a política da capability permitir |

O perfil não incluirá excerpts nem caminhos internos de código.

## 11.2 `helpdesk_copilot`

Destinado a N1, N2 e N3.

Regras padrão:

- incluir CANONICAL, PROVISIONAL e candidates relevantes;
- manter rótulo e confidence de cada item;
- apresentar hipóteses separadamente de fatos;
- incluir conflitos e questions relacionados;
- incluir evidências conforme nível e autorização do analista;
- permitir navegação para histórico, graph e impact;
- nunca omitir que um item está stale ou fora do escopo exato.

## 11.3 Níveis de detalhe do Copilot

```text
N1: orientação funcional, procedimentos e escalonamento
N2: regras, parâmetros, relações e evidência resumida
N3: evidência completa, código, commit, símbolo e confidence breakdown
```

Um perfil poderá herdar outro perfil e ampliar campos, nunca remover rótulos de segurança.

---

# 12. Política Configurável de Consumo

As políticas deverão ser dados configuráveis por:

```text
global
domain
capability
risk
classification
significance
consumer_profile
```

Campos mínimos:

```yaml
name: Help Desk direct — padrão
consumer_profile: helpdesk_direct
scope_type: global
allowed_statuses:
  - CANONICAL
  - PROVISIONAL
minimum_confidence:
  PROVISIONAL: 0.60
allow_stale: false
allow_conflicted: false
critical_requires_escalation: true
include_evidence_excerpt: false
include_internal_location: false
max_context_tokens: 8000
```

Precedência recomendada:

```text
risk > capability > domain > consumer_profile > global
```

Toda decisão de inclusão ou exclusão deverá registrar a política efetiva e sua proveniência.

---

# 13. Entrada do Help Desk Context Builder

Endpoint principal:

```http
POST /helpdesk/context
```

Request:

```json
{
  "question": "Por que não consigo cancelar esta nota?",
  "consumer_profile": "helpdesk_direct",
  "domain": "finance",
  "capability": "invoice-cancellation",
  "context": {
    "product": "erp",
    "version": "12.4",
    "tenant": "empresa-123",
    "company": "01",
    "branch": "03",
    "module": "faturamento",
    "screen": "cancelamento-nota",
    "operation": "cancelar",
    "user_role": "faturista",
    "document_state": "autorizada",
    "error_messages": ["Cancelamento fora do prazo permitido"],
    "locale": "pt-BR"
  },
  "conversation": {
    "previous_question_ids": [],
    "facts_already_collected": []
  }
}
```

Regras:

- `question` e `consumer_profile` são obrigatórios;
- domain e capability poderão ser omitidos quando existir roteamento confiável;
- contexto desconhecido deverá ser omitido, nunca preenchido por suposição;
- campos sensíveis deverão ser tokenizados ou removidos antes da persistência;
- o chamador não poderá aumentar permissões por meio do request;
- orçamento de tokens virá da política, não diretamente do cliente externo.

---

# 14. Resolução de Contexto

Antes da recuperação, o sistema deverá resolver:

```text
domain
capability
produto
versão
cliente/tenant
módulo
tela/operação
papel/permissão
entidade ou documento
estado atual
mensagem/código de erro
vigência temporal
```

Cada dimensão resolvida deverá possuir:

```json
{
  "value": "invoice-cancellation",
  "source": "explicit|message_match|classifier|conversation|unknown",
  "confidence": 0.94
}
```

Se uma dimensão ausente puder alterar materialmente a resposta, o sistema deverá produzir uma
clarifying question em vez de escolher silenciosamente um valor.

Exemplos:

- "Qual é o status atual da nota?"
- "Em qual empresa/filial ocorre o problema?"
- "Qual mensagem aparece na tela?"
- "Qual versão do produto está em uso?"

O classificador de domain/capability será auxiliar. Uma classificação baixa não deverá bloquear a
busca global autorizada, mas deverá reduzir answerability.

---

# 15. Escopo e Vigência

## 15.1 Dimensões de escopo

O modelo deverá aceitar, sem limitar-se a:

```text
product
version
tenant
customer
company
branch
country
legal_regime
module
screen
operation
user_role
permission
entity_type
document_type
document_state
parameter
integration
```

## 15.2 Origem do escopo

Cada dimensão poderá ser:

```text
EXPLICIT       informada diretamente por fonte ou humano
INFERRED       inferida de path, form, tabela, dataset, configuração ou código
UNKNOWN        relevante, mas não determinada
```

Representação recomendada:

```json
{
  "values": {
    "module": "faturamento",
    "screen": "TFrmCancelamento",
    "document_state": "autorizada"
  },
  "status": "INFERRED",
  "confidence": 0.72,
  "basis": ["form:TFrmCancelamento", "table:notas_fiscais"]
}
```

## 15.3 Compatibilidade de escopo

O matching deverá classificar cada atom como:

```text
EXACT
COMPATIBLE
UNKNOWN
MISMATCH
```

`MISMATCH` será excluído. `UNKNOWN` poderá ser incluído no Copilot e somente será utilizado no Direct
conforme política.

## 15.4 Vigência

O campo `effective` deverá suportar:

```text
valid_from
valid_to
product_versions
source_commits
superseded_by
```

Regras sem vigência conhecida continuarão disponíveis, mas receberão `effective_match=UNKNOWN`.

---

# 16. Recuperação

A recuperação deverá combinar sinais complementares.

## 16.1 Busca exata

Prioridade máxima para:

- códigos de erro;
- mensagens exatas ou padrões de mensagens;
- nomes de tela;
- identificadores funcionais;
- nomes de campos e parâmetros;
- IDs de atoms.

## 16.2 Full-text search

Buscar em:

- title;
- description;
- statement;
- bodies estruturados;
- synonyms;
- mensagens;
- summaries de evidência;
- nomes funcionais de telas, campos e parâmetros.

## 16.3 Busca vetorial

Embeddings deverão ser utilizados no consumo, não apenas em deduplicação e discovery.

O texto de embedding deverá representar adequadamente cada kind, incluindo:

- given/when/then de scenarios;
- steps de processes/procedures;
- condition de exceptions;
- trigger e conditions de transitions;
- inputs, outputs e decision rows;
- texto e significado de messages.

## 16.4 Expansão relacional

Após recuperar os atoms iniciais, expandir seletivamente para:

- regras que governam o processo;
- exceções aplicáveis;
- cenários que exemplificam a regra;
- transições e estados relacionados;
- mensagens disparadas;
- procedimentos de resolução;
- conflitos e questions sobre o mesmo tópico;
- versões superseding relevantes.

A expansão deverá ter limite de profundidade e orçamento de tokens.

## 16.5 Diversidade

O ranking não deverá retornar apenas duplicatas semânticas da mesma regra. O pacote deverá priorizar
uma composição útil de:

```text
regra principal
procedimento
pré-condições
exceções
mensagens
estado/transição
conflitos/questions
```

---

# 17. Ranking

O ranking será explicável e versionado.

Sinais iniciais:

```text
exact_message_match
lexical_similarity
semantic_similarity
capability_match
scope_match
effective_match
lifecycle_weight
confidence
freshness
risk
relation_distance
operational_utility
```

Exemplo inicial de composição, sujeito a calibração:

```text
35% similaridade semântica
20% correspondência textual/exata
15% compatibilidade de escopo e vigência
10% lifecycle e política de consumo
10% confidence
 5% freshness
 5% utilidade operacional
```

Regras duras sempre vencem o score:

- ausência de autorização exclui o atom;
- scope mismatch exclui o atom;
- status proibido pela política exclui o atom;
- conflito poderá bloquear resposta direta;
- risco crítico poderá exigir escalonamento;
- mensagem exata terá prioridade sobre similaridade genérica.

Cada item retornado deverá incluir `retrieval_reason` e os principais sinais do ranking.

---

# 18. Answerability

O BSP deverá classificar se o pacote contém suporte suficiente para o agente responder.

Estados:

```text
SUPPORTED       há suporte suficiente e aplicável
PARTIAL         há orientação útil, mas faltam partes relevantes
INSUFFICIENT    não há suporte suficiente
CONFLICTED      há conflito material para a pergunta
OUT_OF_SCOPE    o contexto não pertence ao conhecimento autorizado/disponível
```

Ação recomendada:

```text
ANSWER
ANSWER_WITH_CAUTION
ASK_CLARIFYING
ESCALATE
```

A decisão deverá ser determinística a partir do pacote e da política sempre que possível.

Exemplo:

```json
{
  "answerability": "PARTIAL",
  "recommended_action": "ASK_CLARIFYING",
  "reason": "A regra depende do estado da nota, que não foi informado.",
  "clarifying_questions": [
    "Qual é o status atual da nota?"
  ]
}
```

---

# 19. Help Desk Context Package

Response conceitual:

```json
{
  "package_version": "1.0",
  "generated_at": "2026-09-07T15:00:00Z",
  "knowledge_snapshot": {
    "database_revision": "...",
    "canonical_commit": "..."
  },
  "request": {
    "question": "Por que não consigo cancelar esta nota?",
    "consumer_profile": "helpdesk_direct"
  },
  "resolved_context": {},
  "policy": {
    "name": "Help Desk direct — finance",
    "provenance": {}
  },
  "answerability": "SUPPORTED",
  "recommended_action": "ANSWER",
  "response_instructions": [
    "Explique os pré-requisitos de cancelamento.",
    "Não exponha caminhos ou trechos de código."
  ],
  "knowledge": [
    {
      "id": "FINANCE.INVOICE-CANCELLATION.RULE.0001",
      "version": 2,
      "label": "PROVISIONAL",
      "kind": "rule",
      "title": "Cancelamento exige nota autorizada",
      "body": {},
      "classification": "OBSERVED_BEHAVIOR",
      "significance": "HIGH",
      "risk": "HIGH",
      "confidence": 0.78,
      "scope_match": "EXACT",
      "effective_match": "COMPATIBLE",
      "freshness": "FRESH",
      "evidence_summaries": [],
      "evidence_refs": [],
      "relations": [],
      "retrieval_reason": []
    }
  ],
  "procedures": [],
  "known_conflicts": [],
  "open_questions": [],
  "clarifying_questions": [],
  "escalation": null,
  "citations": []
}
```

## 19.1 Campos obrigatórios por item

```text
id
version
label
kind
title
body ou statement
classification
confidence
risk
significance
scope
scope_match
effective
effective_match
freshness
retrieval_reason
```

## 19.2 Evidências por perfil

`helpdesk_direct`:

```text
evidence summary amigável
atom citation
sem excerpt
sem repository/path interno
```

`helpdesk_copilot` N1:

```text
evidence summary
tipo da evidência
fonte funcional
```

`helpdesk_copilot` N2/N3:

```text
summary
excerpt conforme autorização
repository
file
start_line/end_line
commit
symbol
mechanism
source_id
```

## 19.3 Segurança do pacote

O pacote deverá conter instruções explícitas:

- usar somente conhecimento incluído;
- não remover rótulos de incerteza internamente;
- não transformar comportamento observado em intenção;
- não inventar passos ausentes;
- não sugerir bypass de autorização;
- não misturar regras de escopos incompatíveis;
- citar atom IDs no log da interação;
- seguir `recommended_action`.

---

# 20. Orçamento de Contexto

O pacote será montado sob orçamento configurável.

Defaults iniciais:

```text
helpdesk_direct: 8.000 tokens
helpdesk_copilot N1: 10.000 tokens
helpdesk_copilot N2: 14.000 tokens
helpdesk_copilot N3: 20.000 tokens
```

Ordem de preservação quando o orçamento for excedido:

1. safety instructions e ação recomendada;
2. regra/procedimento principal;
3. pré-condições e exceções;
4. conflitos e questions relevantes;
5. mensagens e estados;
6. evidence summaries;
7. relações distantes;
8. excerpts técnicos.

O truncamento deverá ocorrer por item completo, nunca cortando JSON ou removendo silenciosamente
rótulos de segurança.

O response deverá informar:

```json
{
  "budget": {
    "maximum_tokens": 8000,
    "estimated_tokens": 6230,
    "items_considered": 84,
    "items_included": 12,
    "truncated": true
  }
}
```

---

# 21. Evolução do Business Semantic IR

## 21.1 Kinds já existentes a serem extraídos

O discovery dirigido deverá passar a produzir também:

```text
process
transition
event
exception
```

Além dos kinds já produzidos:

```text
rule
invariant
concept
decision
state
scenario
```

## 21.2 Kind `message`

Representa mensagem visível, erro, aviso ou código operacional relevante.

Body sugerido:

```yaml
text: Cancelamento fora do prazo permitido
code: CAN-014
severity: error
channel: ui
meaning: A nota excedeu o prazo configurado para cancelamento.
variables:
  - prazo
```

## 21.3 Kind `procedure`

Representa orientação operacional para atingir um objetivo ou resolver um problema.

Body sugerido:

```yaml
goal: Cancelar uma nota ainda elegível
audience:
  - faturista
prerequisites:
  - A nota deve estar autorizada.
steps:
  - order: 1
    action: Abrir a tela de cancelamento.
    expected_result: A nota é carregada.
  - order: 2
    action: Informar a justificativa.
    expected_result: O botão Confirmar é habilitado.
success_criteria:
  - Status da nota alterado para cancelada.
escalation_conditions:
  - A mensagem CAN-014 continuar após validação do prazo.
```

Procedures poderão ser criadas por:

- extração do código e UI;
- composição a partir de process/scenario/rule;
- resolução confirmada de ticket;
- contribuição humana.

## 21.4 Novas relações

Adicionar quando necessário:

```text
INDICATES
RESOLVED_BY
APPLIES_TO
```

Exemplos:

```text
message --INDICATES--> exception
message --RESOLVED_BY--> procedure
procedure --APPLIES_TO--> process
rule --EXEMPLIFIED_BY--> scenario
```

As relações existentes continuarão preferidas quando representarem corretamente a semântica.

---

# 22. Discovery Orientado a Help Desk

Criar um modo de discovery `helpdesk` ou uma especialização do discovery dirigido.

Ele deverá procurar explicitamente:

- mensagens apresentadas ao usuário;
- validações de campos;
- condições que habilitam/desabilitam ações;
- permissões e perfis;
- estados requeridos;
- sequência operacional;
- parâmetros que alteram o comportamento;
- tratamento de erros;
- causas e workarounds observáveis;
- transições;
- exceções;
- diferenças por produto, versão, cliente e empresa.

O schema de saída deverá aceitar:

- `scope`;
- `effective`;
- referências temporárias entre candidates do mesmo run;
- relações;
- process, transition, event, exception, message e procedure;
- clarifying questions;
- evidências com symbol e mechanism.

O agente não deverá escrever um procedimento como fato quando o código apenas prova uma validação.
Nesse caso, poderá criar a regra e uma question sobre o procedimento operacional.

---

# 23. Construção Automática de Relações

O graph não poderá depender apenas de relações manuais.

O pipeline deverá incluir uma etapa de linking após a ingestão:

1. resolver referências explícitas produzidas no mesmo run;
2. sugerir relações por IDs, símbolos, mensagens, tabelas, forms e datasets comuns;
3. recuperar atoms semanticamente próximos;
4. pedir ao agente um veredito limitado aos IDs fornecidos;
5. validar mecanicamente os IDs;
6. criar relações com actor, modelo e justificativa auditáveis.

Relações inferidas deverão ter provenance e poderão possuir confidence própria.

O sistema nunca deverá aceitar IDs inventados pelo modelo.

---

# 24. Knowledge Freshness

## 24.1 Estados

```text
FRESH               evidência verificada no snapshot vigente
POTENTIALLY_STALE   a source avançou e o impacto ainda não foi calculado
STALE               o arquivo/faixa/símbolo que sustentava a evidência mudou
UNKNOWN             não foi possível comparar com a source atual
```

## 24.2 Detecção

Ao observar um novo commit da Source:

1. calcular arquivos alterados desde o commit da evidência;
2. identificar evidências nos arquivos alterados;
3. quando possível, comparar símbolo e faixa;
4. marcar evidências afetadas;
5. agregar freshness por atom;
6. agendar discovery/corroboration apenas para atoms afetados;
7. reavaliar confidence e roteamento;
8. preservar histórico e último comportamento conhecido.

## 24.3 Agregação por atom

Regra inicial:

- todas as evidências relevantes vigentes: `FRESH`;
- alguma evidência mudou, mas outras independentes permanecem: `POTENTIALLY_STALE`;
- evidência principal mudou ou desapareceu: `STALE`;
- Source inacessível ou commit desconhecido: `UNKNOWN`.

O cálculo deverá registrar explicação.

## 24.4 Uso

Freshness não apagará conhecimento.

Ela influenciará:

- ranking;
- answerability;
- política de resposta direta;
- prioridade de rediscovery;
- alertas a analistas;
- auditoria de respostas.

---

# 25. Feedback Operacional

## 25.1 Interação

Toda solicitação de contexto deverá poder gerar uma interação auditável:

```text
interaction_id
timestamp
consumer/application
consumer_profile
user/agent pseudonymized
question redacted ou hash
resolved context
policy efetiva
atom IDs e versões utilizados
answerability
recommended action
latência
token budget
```

O conteúdo integral da pergunta/resposta dependerá da política de privacidade.

## 25.2 Resultados

Estados iniciais:

```text
RESOLVED
PARTIALLY_RESOLVED
ESCALATED
REOPENED
INCORRECT
ABANDONED
UNKNOWN
```

## 25.3 Feedback explícito

O consumidor poderá registrar:

```http
POST /helpdesk/interactions/{id}/feedback
```

Payload conceitual:

```json
{
  "outcome": "RESOLVED",
  "helpful_atom_ids": ["..."],
  "misleading_atom_ids": [],
  "missing_information": null,
  "correction": null,
  "ticket_reference": "external:masked"
}
```

## 25.4 Efeito do feedback

Feedback poderá alterar:

- utilidade operacional para ranking;
- priorização de coverage/discovery;
- relatórios de qualidade;
- fila de correções.

Feedback não poderá alterar automaticamente:

- statement;
- classification;
- lifecycle status;
- confidence semântica;
- canonical knowledge.

## 25.5 Correção como candidate

Quando um analista informar correção ou resolução:

1. registrar o feedback imutavelmente;
2. gerar candidate atom ou candidate evidence;
3. classificar a fonte como `TICKET`, `HUMAN_REVIEW` ou `DOMAIN_EXPERT` conforme autoria;
4. relacionar com os atoms utilizados na resposta original;
5. executar dedup e conflito;
6. seguir o lifecycle normal.

Tickets repetidos não deverão ser considerados evidências independentes quando derivarem da mesma
resposta ou procedimento.

---

# 26. Utilidade Operacional

Criar um score separado de confidence semântica.

```text
confidence = quão sustentado está o conhecimento
operational_utility = quão útil ele tem sido nos atendimentos
```

Sinais possíveis:

- quantidade de interações em que o atom foi utilizado;
- resolução associada;
- escalonamento associado;
- reabertura;
- marcação como misleading;
- recência do uso;
- diversidade de tickets e usuários;
- posição em que o atom foi recuperado.

O score de utilidade deverá possuir proteção contra:

- duplicidade de eventos;
- feedback automatizado em massa;
- popularidade de um workaround incorreto;
- correlação falsa entre atom e resolução;
- manipulação por um único consumidor.

---

# 27. Segurança e Autorização

## 27.1 Autorização escopada

Todos os endpoints de consumo deverão aplicar role bindings por domain/capability, não apenas exigir
um usuário autenticado.

O serviço deverá suportar identidades de máquina com:

- nome da aplicação;
- escopos autorizados;
- consumer profiles permitidos;
- expiração e rotação de credencial;
- audit individualizado;
- rate limit.

## 27.2 Separação de conteúdo

O perfil Direct não deverá receber:

- excerpts de código;
- repository paths;
- vulnerabilidades;
- detalhes de implementação desnecessários;
- dados de outros tenants;
- procedimentos de bypass;
- informações internas de segurança.

## 27.3 Dados pessoais

Antes de persistir interação:

- remover ou tokenizar identificadores pessoais;
- aplicar política de retenção;
- restringir acesso aos logs;
- evitar armazenar anexos e payloads completos por padrão;
- permitir exclusão conforme política corporativa sem destruir audit técnico agregado.

## 27.4 Prompt injection

Texto de ticket, mensagem de usuário e documentação serão tratados como dados, não como instruções.

O pacote deverá separar estruturalmente:

```text
system instructions
consumer policy
knowledge
untrusted user content
```

---

# 28. API

Endpoints iniciais:

```text
POST /helpdesk/context
GET  /helpdesk/interactions/{id}
POST /helpdesk/interactions/{id}/feedback
GET  /helpdesk/metrics
GET  /helpdesk/gaps
GET  /helpdesk/policies
POST /helpdesk/policies
PATCH /helpdesk/policies/{id}
POST /helpdesk/evaluate
```

Endpoints de apoio reutilizados:

```text
GET /knowledge/{id}
GET /knowledge/{id}/evidence
GET /knowledge/{id}/confidence
GET /knowledge/{id}/history
GET /knowledge/{id}/impact
GET /graph
```

O endpoint `/context` atual continuará compatível. Ele deverá receber um parâmetro explícito
`include_provisional`, com default `false`, para manter o contrato canonical-only geral.

---

# 29. Canonical Repository e Portabilidade

O YAML canônico deverá passar a exportar também:

```text
significance
evidence mechanism
evidence symbol
source commit
```

`symbol` poderá permanecer dentro de `location`. `mechanism` deverá ser preservado explicitamente.

Freshness é um estado operacional relativo à Source atual e não precisa alterar retroativamente o
artefato histórico. Um snapshot de consumo poderá anexar freshness ao carregar o canonical repo.

Consumers do repositório deverão ignorar por padrão atoms `SUPERSEDED` como conhecimento vigente.

O semantic compiler deverá validar:

- kinds adicionais;
- bodies de message e procedure;
- novas relações;
- referências de procedure/message;
- consistência de version/effective;
- formato de scope;
- presença de campos mínimos para consumo de Help Desk.

---

# 30. Observabilidade e Auditoria

Cada geração de pacote deverá registrar:

- versão do algoritmo de retrieval/ranking;
- política efetiva;
- query normalizada;
- filtros aplicados;
- itens considerados, excluídos e incluídos;
- motivos de exclusão;
- score e sinais dos itens incluídos;
- snapshot da base;
- latência por etapa;
- orçamento e truncamento;
- consumer e perfil;
- answerability e ação recomendada.

Não será necessário guardar embeddings ou raciocínio interno do modelo.

---

# 31. Métricas

## 31.1 Qualidade de recuperação

```text
Retrieval Recall@K
Mean Reciprocal Rank
Exact Message Match Rate
Scope Match Accuracy
Relevant Context Rate
Context Token Efficiency
```

## 31.2 Qualidade de resposta

```text
Supported Answer Rate
Unsupported Assertion Rate
Correct Unknown Rate
Confident Wrong Answer Rate
Clarification Success Rate
Escalation Appropriateness
Stale Knowledge Exposure Rate
```

## 31.3 Resultado operacional

```text
First Contact Resolution
Deflection Rate
Escalation Rate
Reopen Rate
Average Handle Time
Median Time to Resolution
N1 → N2 → N3 Transfer Rate
Feedback Completion Rate
```

## 31.4 Coverage orientado pela demanda

```text
% das perguntas com SUPPORTED
% com PARTIAL
% com INSUFFICIENT
% com CONFLICTED
top unanswered intents
top missing capabilities
top stale atoms utilizados
top misleading atoms
```

Automation Rate não deverá ser otimizada isoladamente. Uma automação alta com alto reopen ou
confident wrong answer rate será considerada regressão.

---

# 32. Avaliação

## 32.1 Dataset

Criar um conjunto versionado de tickets reais anonimizados contendo:

```text
pergunta inicial
contexto disponível
perguntas de clarificação necessárias
resolução final
nível que resolveu
atoms esperados quando conhecidos
resposta aceitável
respostas perigosas/inaceitáveis
```

O gold-standard inicial poderá ser imperfeito, mas deverá indicar sua autoria e nível de validação.

## 32.2 Modos de avaliação

1. **Offline replay:** reproduzir tickets históricos;
2. **Shadow mode:** gerar contexto/resposta sem mostrar ao atendente;
3. **Copilot:** analista decide se utiliza a sugestão;
4. **Direct canary:** pequena parcela de intents/capabilities autorizadas;
5. **Expansão progressiva:** baseada em métricas e limites de risco.

## 32.3 Avaliação separada

Medir separadamente:

- qualidade da recuperação do BSP;
- qualidade do pacote;
- qualidade da resposta do agente consumidor;
- resultado do atendimento.

Uma resposta ruim com atoms corretos é problema do respondente. Atoms errados ou irrelevantes no
pacote são problema da base/retrieval. Essa distinção deverá aparecer nos relatórios.

---

# 33. UX para Analistas

O Copilot deverá apresentar primeiro:

```text
orientação sugerida
perguntas de triagem
procedimento
motivo de escalonamento
```

Detalhes progressivos:

```text
Por que esta resposta?
Regras utilizadas
Confiança e status
Escopo e versão
Evidências
Código-fonte
Histórico
Impacto
```

A interface deverá permitir:

- marcar atom como útil;
- marcar atom como enganoso;
- informar informação ausente;
- corrigir orientação;
- criar question;
- associar resolução ao ticket;
- copiar resposta sem copiar metadados internos;
- abrir o atom completo no BSP.

---

# 34. Estratégia de Implementação

## Fase HD-0 — Contratos e políticas

Entregáveis:

- [x] schemas de request/response do Help Desk Context Package;
- [x] enums de consumer profile, answerability, recommended action e freshness;
- [x] política configurável de consumo;
- [x] `include_provisional=false` explícito no `/context` geral;
- [x] inclusão de significance, effective, relations e capability description no contexto JSON;
- [x] renderização completa dos bodies no Markdown;
- [x] testes de compatibilidade.

Critério de saída:

- o mesmo atom produz projeções diferentes e corretamente rotuladas para Direct e Copilot;
- `/context` continua compatível e canonical-only por padrão.

## Fase HD-1 — Recuperação orientada pela pergunta

Entregáveis:

- [x] `POST /helpdesk/context`;
- [x] resolução de domain/capability;
- [x] busca exata de mensagens/códigos;
- [x] full-text ampliado;
- [x] busca vetorial de consumo;
- [x] ranking explicável;
- [x] filtros por status, scope, effective e RBAC;
- [x] orçamento de tokens;
- [x] answerability e recommended action;
- [x] audit de retrieval.

Critério de saída:

- tickets do dataset recuperam pelo menos um atom esperado no top 5 conforme target inicial;
- nenhum atom não autorizado ou scope mismatch entra no pacote.

## Fase HD-2 — Conhecimento operacional

Entregáveis:

- [x] discovery de process, transition, event e exception;
- [x] kinds message e procedure;
- [x] extração de scope/effective;
- [x] linking automático;
- [x] embeddings para todos os kinds consumíveis;
- [x] projeção de procedimentos;
- [x] cobertura de mensagens e validações;
- [x] export/compile atualizado.

Critério de saída:

- perguntas sobre "como fazer", "por que não posso" e "o que significa esta mensagem" recebem
  contexto procedural e não apenas regras isoladas.

## Fase HD-3 — Freshness

Entregáveis:

- [x] observação de novo commit da Source após inventory/discovery;
- [x] diff por arquivo/símbolo/faixa;
- [x] estado de freshness por evidence/atom;
- [ ] reavaliação e rediscovery direcionados;
- [x] freshness no ranking e pacote;
- [x] dashboard de stale knowledge.

Critério de saída:

- alteração em arquivo citado marca os atoms correspondentes sem invalidar atoms não afetados;
- respostas posteriores registram o freshness efetivamente utilizado.

## Fase HD-4 — Feedback e métricas

Entregáveis:

- [x] helpdesk interactions;
- [x] endpoint de feedback idempotente;
- [x] operational utility score;
- [x] correção → candidate/evidence;
- [x] dashboard de outcomes e gaps;
- [x] replay offline por dataset no endpoint de avaliação;
- [ ] shadow mode;
- [x] relatórios por capability, perfil e versão de retrieval.

Critério de saída:

- toda interação avaliada pode ser ligada aos atoms e versões utilizados;
- feedback altera utilidade/ranking sem alterar canonical automaticamente.

## Fase HD-5 — Rollout controlado

Entregáveis:

- [x] configuração por capability;
- [ ] configuração por intents;
- [ ] canary de resposta direta;
- [ ] limites automáticos por qualidade;
- [ ] rollback de política;
- [ ] alertas de confident wrong answers, stale exposure e reabertura;
- [ ] runbook operacional.

Critério de saída:

- uma capability pode ser habilitada, restringida ou desabilitada sem deploy;
- regressões de qualidade interrompem expansão automática.

---

# 35. Acceptance Criteria — Perfis

## AC-HD-PROFILE-01

Dado um atom CANONICAL vigente e autorizado, os perfis Direct e Copilot deverão recebê-lo.

## AC-HD-PROFILE-02

Dado um atom PROVISIONAL observado, não crítico e compatível com o escopo, o Direct poderá recebê-lo
quando a política efetiva autorizar, sempre com rótulo interno preservado.

## AC-HD-PROFILE-03

Dado um candidate abaixo do piso direto, o Direct não poderá utilizá-lo como afirmação, mas o Copilot
poderá recebê-lo como hipótese.

## AC-HD-PROFILE-04

O Direct não deverá receber excerpt, repository path ou mecanismo interno.

## AC-HD-PROFILE-05

N3 autorizado deverá conseguir navegar do item retornado até evidência, arquivo, linhas, commit,
símbolo e confidence breakdown.

---

# 36. Acceptance Criteria — Contexto e Escopo

## AC-HD-SCOPE-01

Dado um atom aplicável somente ao tenant A, uma pergunta do tenant B não deverá recebê-lo.

## AC-HD-SCOPE-02

Quando o estado do documento puder mudar a resposta e não tiver sido informado, a ação recomendada
deverá ser `ASK_CLARIFYING`.

## AC-HD-SCOPE-03

Escopo inferido deverá ser identificado como INFERRED, com confidence e basis.

## AC-HD-SCOPE-04

Um scope mismatch não poderá ser compensado por alta similaridade semântica.

## AC-HD-SCOPE-05

O pacote deverá registrar todas as dimensões usadas para concluir compatibilidade de escopo.

---

# 37. Acceptance Criteria — Recuperação

## AC-HD-RET-01

Uma mensagem de erro exata deverá ter prioridade sobre resultados semanticamente semelhantes.

## AC-HD-RET-02

Cada item retornado deverá conter os principais motivos de recuperação e ranking.

## AC-HD-RET-03

O pacote deverá respeitar seu orçamento de tokens sem produzir JSON inválido.

## AC-HD-RET-04

Known conflicts e open questions relacionados deverão permanecer presentes mesmo quando possuírem
score textual menor que regras semelhantes.

## AC-HD-RET-05

O ranking deverá diversificar regra, procedimento, exceção e mensagem quando todos forem relevantes.

---

# 38. Acceptance Criteria — Answerability

## AC-HD-ANS-01

Ausência de suporte suficiente deverá produzir `INSUFFICIENT`, nunca uma resposta sugerida inventada.

## AC-HD-ANS-02

Conflito material deverá produzir `CONFLICTED` ou escalonamento conforme política.

## AC-HD-ANS-03

Conhecimento parcial útil deverá produzir `PARTIAL` e informar exatamente o que falta.

## AC-HD-ANS-04

Risk CRITICAL deverá obedecer à política de escalonamento independentemente do score de retrieval.

---

# 39. Acceptance Criteria — Freshness

## AC-HD-FRESH-01

Quando o commit da Source avançar sem análise de diff, atoms dependentes deverão ficar
`POTENTIALLY_STALE`.

## AC-HD-FRESH-02

Quando o arquivo/símbolo citado mudar, a evidence correspondente deverá ficar `STALE`.

## AC-HD-FRESH-03

Atoms sustentados exclusivamente por evidence stale não poderão ser tratados como fresh.

## AC-HD-FRESH-04

O histórico deverá preservar qual commit e freshness foram utilizados em uma interação passada.

## AC-HD-FRESH-05

Um novo commit que não altere os arquivos relacionados não deverá invalidar toda a capability.

---

# 40. Acceptance Criteria — Feedback

## AC-HD-FBK-01

Feedback repetido com a mesma chave idempotente não poderá gerar múltiplos eventos.

## AC-HD-FBK-02

Um resultado RESOLVED poderá aumentar operational utility, mas não confidence semântica.

## AC-HD-FBK-03

Uma correção deverá gerar candidate/evidence auditável, sem editar canonical diretamente.

## AC-HD-FBK-04

Deverá ser possível identificar quais atoms foram marcados como misleading em respostas reabertas.

## AC-HD-FBK-05

Dados pessoais não autorizados não deverão aparecer em métricas ou exports.

---

# 41. Acceptance Criteria — Segurança

## AC-HD-SEC-01

Um consumer autorizado apenas para domain A não poderá recuperar atoms do domain B.

## AC-HD-SEC-02

Alterar `consumer_profile` no request não poderá ampliar os privilégios da identidade.

## AC-HD-SEC-03

Texto de usuário que contenha instruções não poderá alterar a consumer policy do pacote.

## AC-HD-SEC-04

O Direct não deverá retornar dados técnicos restritos mesmo quando eles forem semanticamente
relevantes.

## AC-HD-SEC-05

Toda geração deverá registrar consumer, escopo autorizado e política efetiva.

---

# 42. Non-Functional Requirements

## Performance

- p95 de até 2 segundos para geração do pacote sem chamada a LLM;
- busca exata de mensagem em até 500 ms no p95;
- orçamento e quantidade máxima de items configuráveis;
- degradação funcional para full-text quando embeddings estiverem indisponíveis.

## Disponibilidade

- falha do provedor de embeddings não deverá indisponibilizar busca textual;
- falha ao verificar freshness deverá gerar `UNKNOWN`, não apagar conhecimento;
- feedback poderá ser enfileirado quando processamento posterior estiver indisponível.

## Auditabilidade

- decisões de inclusão/exclusão reproduzíveis por versão de algoritmo e política;
- eventos append-only;
- vínculo com atom/version preservado.

## Extensibilidade

- novos consumer profiles sem mudança do lifecycle;
- novas dimensões de scope em JSONB;
- novos retrievers e rerankers por interface;
- integração independente do modelo respondente.

## Segurança

- RBAC/ABAC antes da recuperação;
- secrets fora do pacote;
- rate limiting;
- logs redigidos;
- proteção contra enumeração de atoms não autorizados.

---

# 43. Targets Iniciais

Os targets deverão ser recalibrados com tickets reais.

```text
Retrieval Recall@5 > 85% nas capabilities piloto
Exact Message Match Recall > 95%
Scope Mismatch Exposure < 1%
Unsupported Assertion Rate < 3%
Confident Wrong Answer Rate < 1%
Correct Unknown Rate > 90%
Stale Knowledge Exposure < 2%
p95 do Context Builder < 2 segundos
```

Targets operacionais para Copilot após baseline:

```text
redução de pelo menos 20% no Average Handle Time
redução de pelo menos 15% nas transferências N1 → N2 evitáveis
aumento de pelo menos 15% no First Contact Resolution das intents cobertas
```

Esses targets não deverão bloquear a primeira execução em shadow mode.

---

# 44. Riscos e Mitigações

| Risco | Mitigação |
|---|---|
| Regra correta aplicada no contexto errado | Matching de scope/effective como gate duro |
| Provisório incorreto chegar ao usuário | Política por perfil, risco e capability; feedback e canary |
| SYSTEMIC classificado incorretamente | Auditoria amostral também de auto-approved/systemic |
| Conhecimento antigo continuar respondendo | Freshness por evidence/arquivo/símbolo |
| Feedback popularizar resposta incorreta | Separar operational utility de confidence |
| Pacote grande reduzir qualidade do agente | Retrieval orientado pela pergunta e orçamento de tokens |
| Graph esparso limitar diagnóstico | Linking automático pós-discovery |
| Exposição de código ou dados internos | Projeções por perfil e autorização antes do retrieval |
| Modelo ignorar rótulos | Gates estruturais no servidor; não depender apenas de prompt |
| Falha de embeddings | Fallback full-text e busca exata |
| Tickets conterem PII ou prompt injection | Redação, isolamento estrutural e retenção configurável |

---

# 45. Definition of Done

Esta iniciativa será considerada pronta para piloto quando:

1. os dois consumer profiles estiverem implementados;
2. o Context Package for gerado a partir de pergunta e contexto;
3. retrieval combinar busca exata, full-text e embeddings;
4. scope/effective forem aplicados antes da inclusão;
5. answerability e recommended action forem gerados;
6. Direct e Copilot receberem projeções distintas;
7. atoms retornados forem rastreáveis às evidências;
8. relations, conflicts e questions relevantes entrarem no pacote;
9. orçamento de tokens e truncamento seguro estiverem implementados;
10. RBAC escopado for aplicado aos endpoints de consumo;
11. interações e feedback forem auditáveis;
12. feedback não modificar canonical automaticamente;
13. freshness estiver visível ou explicitamente UNKNOWN;
14. replay offline estiver executável;
15. métricas de retrieval, resposta e resultado estiverem separadas;
16. uma capability real estiver operando em shadow mode;
17. os acceptance criteria da fase liberada estiverem automatizados;
18. houver rollback de política sem deploy.

---

# 46. Decisões Pendentes para o Piloto

As seguintes escolhas não bloqueiam o desenvolvimento da fundação, mas deverão ser definidas antes
de resposta direta em produção:

1. primeiro sistema de Help Desk a integrar;
2. capabilities e intents do piloto;
3. quais riscos nunca poderão usar provisório no Direct;
4. threshold provisório inicial por capability;
5. campos de tenant/empresa/filial disponíveis na integração;
6. política de retenção de perguntas e respostas;
7. forma de pseudonimização de usuário e ticket;
8. identidade de máquina e mecanismo de autenticação;
9. responsáveis por avaliar respostas incorretas;
10. limites que suspendem automaticamente o modo Direct.

Defaults recomendados:

- começar em shadow mode;
- liberar Copilot antes de Direct;
- habilitar Direct por intent, não por domain inteiro;
- permitir provisório observado e não crítico somente com scope compatível;
- escalar risco crítico;
- não persistir conteúdo integral do atendimento por padrão;
- manter rollback de política imediato.

---

# 47. North Star

> Dada uma pergunta real de suporte e seu contexto operacional, o BSP deve entregar o menor conjunto
> de conhecimento necessário para que um agente responda corretamente, explique seus limites,
> saiba quando perguntar ou escalar e permita reconstruir posteriormente por que aquela resposta foi
> produzida.
