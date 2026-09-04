"""Prompts dos Discovery Agents do BSP (PRD §11, §90) + schemas de saída estruturada.

Ao contrário do consultor do Praxis (que PROÍBE citar código), aqui evidence com
arquivo/linhas é OBRIGATÓRIA (P5, AC-EVI-01) — o kernel verifica cada citação
contra o fonte real e rejeita o que não existir.

Todos os agentes recebem o CONTEXTO DE NEGÓCIO (domain e, quando houver, capability com
descrição) e NOTAS DE LINGUAGEM derivadas das extensões dos arquivos do escopo.
"""

import json
from pathlib import Path

# Política de prompt do §90 — preâmbulo comum a todos os agentes
POLICY = """\
Você é um agente de discovery da Business Semantic Platform. Regras invioláveis (PRD §90):

1. NUNCA crie fatos de negócio sem suporte no código/testes analisados.
2. SEMPRE distinga comportamento observado (OBSERVED_BEHAVIOR) de comportamento \
intencional (INTENDED_BEHAVIOR); use LEGACY_QUIRK/KNOWN_BUG quando o código sugerir isso.
3. TODA afirmação precisa de evidence com arquivo + linhas EXATAS que você LEU. \
Cada evidence será verificada mecanicamente contra o fonte: arquivo inexistente ou \
range de linhas inválido invalida a evidence. Nunca cite de memória.
4. Em dúvida, crie uma QUESTION em vez de inventar resposta (UNKNOWN é resultado válido).
5. Prefira regras pequenas e componíveis a regras compostas.
6. Nunca esconda incerteza; nunca atribua confiança — o cálculo de confidence é do sistema.
7. Escreva title/statement/summary em LINGUAGEM DE NEGÓCIO, em português, para leigos \
(o summary de cada evidence é a tradução amigável que um revisor de negócio lerá).
8. RÉGUA DE RELEVÂNCIA. Conhecimento de negócio é o que um gestor da área reconheceria como \
regra, política, cálculo, condição, limite com significado de negócio, transição de estado \
ou exceção. NÃO é conhecimento de negócio, e NÃO deve virar candidate:
   - validação genérica de entrada: campo obrigatório, formato/máscara, data inicial maior \
que a final, número positivo, tamanho máximo de texto, CPF/CNPJ com dígito inválido;
   - comportamento de interface: habilitar/desabilitar botão, foco, paginação, ordenação, \
mensagem de confirmação, atalho de teclado;
   - infraestrutura: log, conexão, transação, cache, retry, permissão genérica de tela, \
tratamento técnico de erro, mapeamento de campos.
   Classifique cada candidate em `significance`:
   - HIGH: muda dinheiro, imposto, estoque, comissão, status de documento ou uma decisão \
do negócio; políticas, exceções e regras legais/fiscais.
   - MEDIUM: regra operacional de processo, cálculo auxiliar, condição que altera o fluxo.
   - LOW: detalhe operacional com algum significado de negócio (ex.: valor padrão de um \
parâmetro comercial, arredondamento de exibição).
   - TRIVIAL: caiu numa das exclusões acima. Prefira não emitir; se emitir, será descartado.
"""

# ---------- linguagem ----------

LANGUAGES: dict[str, tuple[str, str]] = {
    # ext: (nome, nota para o agente — onde mora regra de negócio e como são os testes)
    ".pas": ("Delphi/Object Pascal",
             "regras costumam estar em units de negócio (procedures/functions, validações em "
             "eventos de DataSet como BeforePost, e SQL embutido em strings); arquivos .dfm são "
             "layout de formulário (raramente regra); testes usam DUnit/DUnitX."),
    ".dpr": ("Delphi/Object Pascal", "arquivo de projeto: inicialização, pouca regra de negócio."),
    ".dpk": ("Delphi/Object Pascal", "pacote: lista de units, sem regra de negócio."),
    ".inc": ("Delphi/Object Pascal", "include: constantes e diretivas."),
    ".java": ("Java",
              "regras em services/domain/entities; validações em anotações (Bean Validation) "
              "e exceções de negócio; testes em JUnit/TestNG (src/test)."),
    ".kt": ("Kotlin", "regras em services/domain; testes JUnit/Kotest."),
    ".cs": ("C#", "regras em services/domain; validações em atributos; testes xUnit/NUnit/MSTest."),
    ".vb": ("Visual Basic .NET", "regras em módulos/classes de negócio; testes MSTest/NUnit."),
    ".go": ("Go", "regras em pacotes de domínio; testes *_test.go."),
    ".py": ("Python", "regras em services/models/validators; testes pytest (test_*.py)."),
    ".rb": ("Ruby", "regras em models/services; validações ActiveRecord; testes RSpec/Minitest."),
    ".php": ("PHP", "regras em services/models; testes PHPUnit."),
    ".ts": ("TypeScript", "regras em services/domain; testes Jest/Vitest (*.spec.ts, *.test.ts)."),
    ".tsx": ("TypeScript/React", "componentes: validações de formulário podem codificar regra."),
    ".js": ("JavaScript", "regras em services; testes Jest/Mocha."),
    ".mjs": ("JavaScript", "módulos ES."),
    ".sql": ("SQL", "constraints, triggers e procedures codificam invariantes e regras."),
    ".prw": ("ADVPL (Protheus)",
             "pontos de entrada e funções de usuário codificam regras fiscais/comerciais."),
    ".tlpp": ("TL++ (Protheus)", "regras em classes/funções de negócio."),
    ".c": ("C", "regras em funções; testes CUnit/Check."),
    ".cpp": ("C++", "regras em classes de domínio; testes GoogleTest/Catch2."),
    ".h": ("C/C++", "declarações."),
    ".cbl": ("COBOL", "regras em PROCEDURE DIVISION; validações em EVALUATE/IF."),
    ".cob": ("COBOL", "regras em PROCEDURE DIVISION."),
    ".rs": ("Rust", "regras em módulos de domínio; testes #[test]."),
    ".scala": ("Scala", "regras em services/domain; testes ScalaTest."),
    ".groovy": ("Groovy", "regras em services; testes Spock."),
    ".swift": ("Swift", "regras em modelos/serviços; testes XCTest."),
}


def language_of(path: str) -> str | None:
    info = LANGUAGES.get(Path(path).suffix.lower())
    return info[0] if info else None


def language_notes(paths: list[str]) -> str:
    """Notas de linguagem para as extensões presentes (ordem por frequência)."""
    contagem: dict[str, int] = {}
    for p in paths:
        ext = Path(p).suffix.lower()
        if ext in LANGUAGES:
            contagem[ext] = contagem.get(ext, 0) + 1
    if not contagem:
        return ""
    vistas: set[str] = set()
    linhas = []
    for ext, _ in sorted(contagem.items(), key=lambda kv: -kv[1]):
        nome, nota = LANGUAGES[ext]
        if nome in vistas:
            continue
        vistas.add(nome)
        linhas.append(f"- {nome} ({ext}): {nota}")
    return "Linguagens do escopo e onde procurar regra de negócio:\n" + "\n".join(linhas)


# ---------- contexto de negócio ----------


def business_context(
    domain: str | None,
    capability: dict | None = None,
    capabilities: list[dict] | None = None,
) -> str:
    """Bloco com domain/capability(ies). `capability`/`capabilities` são dicts
    {slug, name, description?}."""
    if not domain and not capability and not capabilities:
        return ""
    partes = ["## Contexto de negócio"]
    if domain:
        partes.append(f"Domain: **{domain}**")
    if capability:
        desc = f" — {capability['description']}" if capability.get("description") else ""
        partes.append(
            f"Capability alvo: **{capability['name']}** (slug `{capability['slug']}`){desc}\n"
            "Extraia SOMENTE conhecimento que pertença a esta capability. O que for de outra "
            "área de negócio, ignore (ou registre como question se for relevante para esta)."
        )
    if capabilities:
        partes.append("Capabilities cadastradas neste domain:")
        for c in capabilities:
            desc = f" — {c['description']}" if c.get("description") else ""
            partes.append(f"- `{c['slug']}` {c['name']}{desc}")
    return "\n".join(partes) + "\n"


# ---------- schemas ----------

_EVIDENCE_ITEM = {
    "type": "object",
    "required": ["file", "start_line", "end_line", "summary"],
    "properties": {
        "file": {"type": "string", "description": "caminho relativo à raiz do workspace"},
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
        "summary": {
            "type": "string",
            "description": "tradução de negócio do que este trecho evidencia",
        },
    },
}

_CANDIDATE_ITEM = {
    "type": "object",
    "required": ["kind", "title", "statement", "classification", "significance", "evidence"],
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
        "significance": {
            "type": "string",
            "enum": ["TRIVIAL", "LOW", "MEDIUM", "HIGH"],
            "description": "relevância de negócio (regra 8): TRIVIAL será descartado",
        },
        "decision_inputs": {"type": "array", "items": {"type": "string"}},
        "decision_output": {"type": "string"},
        "scenario_given": {"type": "string"},
        "scenario_when": {"type": "string"},
        "scenario_then": {"type": "string"},
        "evidence": {"type": "array", "minItems": 1, "items": _EVIDENCE_ITEM},
    },
}

_QUESTION_ITEM = {
    "type": "object",
    "required": ["question"],
    "properties": {"question": {"type": "string"}, "context": {"type": "string"}},
}

DISCOVERY_SCHEMA = {
    "type": "object",
    "required": ["candidates", "questions"],
    "properties": {
        "candidates": {"type": "array", "items": _CANDIDATE_ITEM},
        "questions": {"type": "array", "items": _QUESTION_ITEM},
    },
}

# Discovery dirigido: além de candidates/questions, o agente pode (a) REFORÇAR conhecimento
# já registrado citando este arquivo como evidência adicional, em vez de duplicar, e
# (b) pedir turnos extras em arquivos relacionados que não cabiam neste turno.
DIRECTED_SCHEMA = {
    "type": "object",
    "required": ["candidates", "questions", "reinforcements", "followups"],
    "properties": {
        "candidates": {"type": "array", "items": _CANDIDATE_ITEM},
        "questions": {"type": "array", "items": _QUESTION_ITEM},
        "reinforcements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["atom_id", "evidence"],
                "properties": {
                    "atom_id": {
                        "type": "string",
                        "description": "id de um item da lista de conhecimento já registrado",
                    },
                    "note": {"type": "string"},
                    "evidence": {"type": "array", "minItems": 1, "items": _EVIDENCE_ITEM},
                },
            },
        },
        "followups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["file", "reason"],
                "properties": {
                    "file": {"type": "string", "description": "caminho relativo ao workspace"},
                    "reason": {"type": "string"},
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
                    "evidence": {"type": "array", "items": _EVIDENCE_ITEM},
                },
            },
        }
    },
}

INVENTORY_SCHEMA = {
    "type": "object",
    "required": ["files", "suggested_capabilities"],
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "summary", "capabilities"],
                "properties": {
                    "path": {"type": "string", "description": "exatamente como recebido"},
                    "summary": {
                        "type": "string",
                        "description": "1-2 frases: o que este arquivo faz, em termos de negócio",
                    },
                    "capabilities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["slug", "relevance"],
                            "properties": {
                                "slug": {"type": "string"},
                                "relevance": {
                                    "type": "integer", "minimum": 1, "maximum": 3,
                                    "description": "3 central · 2 relevante · 1 tangencial",
                                },
                                "note": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "suggested_capabilities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "rationale"],
                "properties": {
                    "name": {"type": "string"},
                    "rationale": {"type": "string"},
                    "example_files": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


# ---------- prompts ----------


def code_discovery_prompt(
    scope_hint: str,
    max_candidates: int = 40,
    *,
    domain: str | None = None,
    capability: dict | None = None,
    languages: str = "",
) -> str:
    return f"""{POLICY}
{business_context(domain, capability)}
## Sua tarefa: CODE DISCOVERY

Analise o código-fonte deste repositório e extraia o CONHECIMENTO DE NEGÓCIO implícito:
regras, invariantes, conceitos, decisões, estados e cenários que o código impõe.

Escopo prioritário desta varredura: {scope_hint}
{languages}
Método:
1. Explore a estrutura do repositório para entender os módulos do escopo.
2. Leia os arquivos relevantes de verdade (as linhas citadas serão verificadas).
   Ignore binários e artefatos de build (.dcu, .res, .bpi, .exe, .jar, .class, .dll).
3. Para cada comportamento de negócio encontrado, produza um candidate com evidence
   apontando as linhas exatas. Comportamento técnico puro (imports, logging, boilerplate)
   NÃO é conhecimento de negócio — ignore.
4. Registre como question tudo que ficou ambíguo ou contraditório.

Limite-se aos {max_candidates} candidates mais relevantes de negócio.
Ao final, emita APENAS a saída estruturada conforme o schema."""


def test_discovery_prompt(
    scope_hint: str,
    max_candidates: int = 40,
    *,
    domain: str | None = None,
    capability: dict | None = None,
    languages: str = "",
) -> str:
    return f"""{POLICY}
{business_context(domain, capability)}
## Sua tarefa: TEST DISCOVERY

Analise APENAS os testes automatizados deste repositório. Testes codificam comportamento
esperado: cada asserção relevante de negócio é uma evidência de regra/cenário.

Escopo prioritário desta varredura: {scope_hint}
{languages}
Método:
1. Localize os arquivos de teste do escopo (use as convenções da linguagem acima:
   DUnit/DUnitX, JUnit, pytest, *_test.go, *.spec.ts etc.).
2. Leia os testes e extraia as regras/cenários de negócio que eles garantem
   (evidence = linhas do TESTE, não do código de produção).
3. Prefira kind=scenario para casos concretos (given/when/then) e kind=rule para a
   regra geral que o teste garante.
4. Registre como question comportamentos testados que pareçam contraditórios.

Limite-se aos {max_candidates} candidates mais relevantes de negócio.
Ao final, emita APENAS a saída estruturada conforme o schema."""


def corroboration_prompt(
    candidates: list[dict],
    *,
    domain: str | None = None,
    capability: dict | None = None,
    languages: str = "",
) -> str:
    listagem = "\n".join(
        f"- {c['atom_id']}: {c['statement']}" for c in candidates
    )
    return f"""{POLICY}
{business_context(domain, capability)}
## Sua tarefa: CORROBORATION (PRD §88)

Abaixo estão afirmações de negócio candidatas extraídas deste repositório por OUTRO
agente. Para cada uma, procure INDEPENDENTEMENTE no repositório evidência que a
sustente ou contradiga — leia os arquivos de verdade e cite linhas exatas.
{languages}
Vereditos:
- SUPPORTS: você encontrou evidência que sustenta a afirmação (cite-a);
- CONTRADICTS: você encontrou evidência de comportamento diferente (cite-a);
- NOT_FOUND: você não encontrou evidência relevante (evidence vazia; não invente).

Afirmações a corroborar:
{listagem}

Ao final, emita APENAS a saída estruturada conforme o schema, com um finding por afirmação."""


FILE_MARK = "### ARQUIVO: "  # marcador estável (o fake de teste e o parser dependem dele)


def _bloco_arquivo(path: str, content: str, *, truncated: bool = False, numbered: bool = False,
                   start_line: int = 1) -> str:
    if numbered:
        linhas = content.splitlines()
        largura = len(str(start_line + len(linhas)))
        content = "\n".join(
            f"{i:>{largura}}| {ln}" for i, ln in enumerate(linhas, start=start_line)
        )
    aviso = "\n[... arquivo truncado para o inventário ...]" if truncated else ""
    return f"{FILE_MARK}{path}\n```\n{content}{aviso}\n```\n"


def inventory_prompt(
    *,
    domain: str,
    capabilities: list[dict],
    files: list[dict],
) -> str:
    """files: [{path, content, truncated, lines}]. Conteúdo vai EMBUTIDO: o agente não
    precisa gastar turnos abrindo arquivo por arquivo."""
    blocos = "\n".join(
        _bloco_arquivo(f["path"], f["content"], truncated=f.get("truncated", False))
        for f in files
    )
    caps = business_context(domain, None, capabilities)
    langs = language_notes([f["path"] for f in files])
    return f"""{POLICY}
{caps}
## Sua tarefa: INVENTÁRIO DE FONTES

Abaixo estão {len(files)} arquivos-fonte deste repositório (conteúdo incluído). Para CADA um:
1. Resuma em 1-2 frases o que ele faz, em termos de negócio (não técnicos).
2. Ligue-o às capabilities cadastradas acima com relevance 3 (central: o arquivo implementa
   regras desta capability), 2 (relevante: participa dela) ou 1 (tangencial: só a referencia).
   Um arquivo pode ligar-se a várias capabilities ou a nenhuma (lista vazia).
   Use SOMENTE slugs cadastrados.
3. Se encontrar uma área de negócio clara que NÃO tem capability cadastrada, registre em
   suggested_capabilities (nome de negócio, justificativa e arquivos de exemplo).

Infraestrutura pura (conexão, log, utilitários genéricos) fica sem capability.
Devolva um item em `files` para CADA arquivo recebido, com o `path` exatamente igual.
{langs}

{blocos}
Ao final, emita APENAS a saída estruturada conforme o schema."""


def directed_discovery_prompt(
    *,
    domain: str,
    capability: dict,
    file: str,
    content: str,
    start_line: int,
    end_line: int,
    total_lines: int,
    max_candidates: int,
    file_summary: str | None = None,
    related_files: list[dict] | None = None,
    existing: list[dict] | None = None,
) -> str:
    """Um turno = um arquivo (ou uma faixa de linhas dele) para UMA capability.
    O conteúdo vem NUMERADO (números absolutos) para que as citações batam exatamente.
    `existing`: conhecimento já registrado mais próximo deste arquivo (recuperação vetorial),
    [{atom_id, title, statement, status}] — o agente reforça em vez de duplicar."""
    faixa = (
        f"linhas {start_line}-{end_line} de {total_lines}"
        if (start_line, end_line) != (1, total_lines)
        else f"{total_lines} linhas (arquivo completo)"
    )
    resumo = f"\nResumo do inventário sobre este arquivo: {file_summary}\n" if file_summary else ""
    relacionados = ""
    if related_files:
        itens = "\n".join(
            f"- {r['path']}" + (f" — {r['summary']}" if r.get("summary") else "")
            for r in related_files
        )
        relacionados = (
            "\nOutros arquivos ligados a esta capability pelo inventário (abra com Read só se "
            f"precisar de contexto; cite-os apenas se LER as linhas):\n{itens}\n"
        )
    langs = language_notes([file])
    conhecido = ""
    if existing:
        itens = "\n".join(
            f"- `{e['atom_id']}` [{e.get('status', '')}] {e['title']}"
            + (f" — {e['statement']}" if e.get("statement") else "")
            for e in existing
        )
        conhecido = f"""
## Conhecimento JÁ registrado nesta área (os {len(existing)} mais próximos deste arquivo)
{itens}

Regra de ouro: NÃO crie candidate para algo que já está na lista, mesmo com outra redação.
- Se este arquivo EVIDENCIA um item da lista (implementa, valida ou testa a mesma regra),
  registre em `reinforcements` com o atom_id e as linhas exatas deste arquivo. Evidência de
  arquivo diferente é fonte independente e aumenta a confiança daquele conhecimento.
- Se este arquivo CONTRADIZ ou mostra que um item está incompleto/errado, registre uma
  question citando o atom_id e as linhas — não crie um candidate concorrente.
- Crie candidate SOMENTE para conhecimento novo, ausente da lista.
"""
    return f"""{POLICY}
{business_context(domain, capability)}
## Sua tarefa: DISCOVERY DIRIGIDO — um arquivo, uma capability

Arquivo alvo: `{file}` ({faixa}). O conteúdo está abaixo com número de linha à esquerda
(`NNN| código`): use ESSES números nas citações (start_line/end_line).{resumo}{relacionados}
{langs}
{conhecido}
Método:
1. Leia o trecho abaixo por completo.
2. Extraia SÓ o conhecimento de negócio da capability alvo: regras, invariantes, decisões,
   estados, cenários. Comportamento técnico puro não conta.
3. Cada candidate cita as linhas exatas deste arquivo (ou de outro que você LEU com Read).
4. Ambiguidades e contradições viram questions.
5. Se este trecho depender de outra unidade/classe para entender uma regra desta
   capability e ela não estiver na lista acima, registre em followups (arquivo + motivo).
   Não invente caminhos: só arquivos que você viu referenciados ou localizou com Glob/Grep.

Limite-se aos {max_candidates} candidates NOVOS mais relevantes (reforços não contam no limite).

{_bloco_arquivo(file, content, numbered=True, start_line=start_line)}
Ao final, emita APENAS a saída estruturada conforme o schema."""


def schema_json(schema: dict) -> str:
    return json.dumps(schema, ensure_ascii=False)
