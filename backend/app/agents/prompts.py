"""Prompts dos Discovery Agents do BSP (PRD §11, §90) + schemas de saída estruturada.

Ao contrário do consultor do Praxis (que PROÍBE citar código), aqui evidence com
arquivo/linhas é OBRIGATÓRIA (P5, AC-EVI-01) — o kernel verifica cada citação
contra o commit real e rejeita o que não existir.
"""

import json

# Política de prompt do §90 — preâmbulo comum a todos os agentes
POLICY = """\
Você é um agente de discovery da Business Semantic Platform. Regras invioláveis (PRD §90):

1. NUNCA crie fatos de negócio sem suporte no código/testes analisados.
2. SEMPRE distinga comportamento observado (OBSERVED_BEHAVIOR) de comportamento \
intencional (INTENDED_BEHAVIOR); use LEGACY_QUIRK/KNOWN_BUG quando o código sugerir isso.
3. TODA afirmação precisa de evidence com arquivo + linhas EXATAS que você LEU. \
Cada evidence será verificada mecanicamente contra o commit: arquivo inexistente ou \
range de linhas inválido invalida a evidence. Nunca cite de memória.
4. Em dúvida, crie uma QUESTION em vez de inventar resposta (UNKNOWN é resultado válido).
5. Prefira regras pequenas e componíveis a regras compostas.
6. Nunca esconda incerteza; nunca atribua confiança — o cálculo de confidence é do sistema.
7. Escreva title/statement/summary em LINGUAGEM DE NEGÓCIO, em português, para leigos \
(o summary de cada evidence é a tradução amigável que um revisor de negócio lerá).
"""

_CANDIDATE_ITEM = {
    "type": "object",
    "required": ["kind", "title", "statement", "classification", "evidence"],
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["rule", "invariant", "concept", "decision", "state", "scenario"],
        },
        "title": {"type": "string", "maxLength": 200},
        "statement": {
            "type": "string",
            "description": "A afirmação de negócio, completa e autocontida",
        },
        "description": {"type": "string"},
        "classification": {
            "type": "string",
            "enum": [
                "OBSERVED_BEHAVIOR",
                "INTENDED_BEHAVIOR",
                "MANDATED_BEHAVIOR",
                "LEGACY_QUIRK",
                "KNOWN_BUG",
                "DEPRECATED_BEHAVIOR",
                "UNKNOWN",
            ],
        },
        "risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
        "decision_inputs": {"type": "array", "items": {"type": "string"}},
        "decision_output": {"type": "string"},
        "scenario_given": {"type": "string"},
        "scenario_when": {"type": "string"},
        "scenario_then": {"type": "string"},
        "evidence": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["file", "start_line", "end_line", "summary"],
                "properties": {
                    "file": {"type": "string", "description": "caminho relativo à raiz do repo"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                    "summary": {
                        "type": "string",
                        "description": "tradução de negócio do que este trecho evidencia",
                    },
                },
            },
        },
    },
}

DISCOVERY_SCHEMA = {
    "type": "object",
    "required": ["candidates", "questions"],
    "properties": {
        "candidates": {"type": "array", "items": _CANDIDATE_ITEM},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {"type": "string"},
                    "context": {"type": "string"},
                },
            },
        },
    },
}

CORROBORATION_SCHEMA = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["atom_id", "verdict", "evidence"],
                "properties": {
                    "atom_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["SUPPORTS", "CONTRADICTS", "NOT_FOUND"],
                    },
                    "note": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["file", "start_line", "end_line", "summary"],
                            "properties": {
                                "file": {"type": "string"},
                                "start_line": {"type": "integer", "minimum": 1},
                                "end_line": {"type": "integer", "minimum": 1},
                                "summary": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
    },
}


def code_discovery_prompt(scope_hint: str, max_candidates: int = 40) -> str:
    return f"""{POLICY}
## Sua tarefa: CODE DISCOVERY

Analise o código-fonte deste repositório e extraia o CONHECIMENTO DE NEGÓCIO implícito:
regras, invariantes, conceitos, decisões, estados e cenários que o código impõe.

Escopo prioritário desta varredura: {scope_hint}

Método:
1. Explore a estrutura do repositório para entender os módulos do escopo.
2. Leia os arquivos relevantes de verdade (as linhas citadas serão verificadas).
3. Para cada comportamento de negócio encontrado, produza um candidate com evidence
   apontando as linhas exatas. Comportamento técnico puro (imports, logging, boilerplate)
   NÃO é conhecimento de negócio — ignore.
4. Registre como question tudo que ficou ambíguo ou contraditório.

Limite-se aos {max_candidates} candidates mais relevantes de negócio.
Ao final, emita APENAS a saída estruturada conforme o schema."""


def test_discovery_prompt(scope_hint: str, max_candidates: int = 40) -> str:
    return f"""{POLICY}
## Sua tarefa: TEST DISCOVERY

Analise APENAS os testes automatizados deste repositório (arquivos *_test.go, *test*,
specs). Testes codificam comportamento esperado: cada asserção relevante de negócio é
uma evidência de regra/cenário.

Escopo prioritário desta varredura: {scope_hint}

Método:
1. Localize os arquivos de teste do escopo.
2. Leia os testes e extraia as regras/cenários de negócio que eles garantem
   (evidence = linhas do TESTE, não do código de produção).
3. Prefira kind=scenario para casos concretos (given/when/then) e kind=rule para a
   regra geral que o teste garante.
4. Registre como question comportamentos testados que pareçam contraditórios.

Limite-se aos {max_candidates} candidates mais relevantes de negócio.
Ao final, emita APENAS a saída estruturada conforme o schema."""


def corroboration_prompt(candidates: list[dict]) -> str:
    listagem = "\n".join(
        f"- {c['atom_id']}: {c['statement']}" for c in candidates
    )
    return f"""{POLICY}
## Sua tarefa: CORROBORATION (PRD §88)

Abaixo estão afirmações de negócio candidatas extraídas deste repositório por OUTRO
agente. Para cada uma, procure INDEPENDENTEMENTE no repositório evidência que a
sustente ou contradiga — leia os arquivos de verdade e cite linhas exatas.

Vereditos:
- SUPPORTS: você encontrou evidência que sustenta a afirmação (cite-a);
- CONTRADICTS: você encontrou evidência de comportamento diferente (cite-a);
- NOT_FOUND: você não encontrou evidência relevante (evidence vazia; não invente).

Afirmações a corroborar:
{listagem}

Ao final, emita APENAS a saída estruturada conforme o schema, com um finding por afirmação."""


def schema_json(schema: dict) -> str:
    return json.dumps(schema, ensure_ascii=False)
