"""Harness falso para testes: emite stream-json como o `claude -p`.

Cenário via env FAKE_SCENARIO:
  discovery_ok — payload de discovery com candidates/questions (evidence em billing.go)
  corrob_ok    — payload de corroboration (atom id via FAKE_ATOM_ID)
  limit        — simula franquia esgotada (stderr, sem evento de resultado)
  auth         — simula perfil deslogado
  rescue       — 1ª chamada falha com error_max_structured_output_retries; --resume sucede
"""

import json
import os
import re
import sys


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")


def result_event(structured=None, is_error=False, subtype=None, cost=0.42, text="ok"):
    emit(
        {
            "type": "result",
            "subtype": subtype,
            "is_error": is_error,
            "result": text,
            "structured_output": structured,
            "total_cost_usd": cost,
            "num_turns": 3,
            "session_id": "sess-fake-1",
        }
    )


def main() -> int:
    if "--version" in sys.argv:
        print("9.9.9 (Claude Code fake)")
        return 0
    prompt = sys.stdin.read()  # o prompt: inventário/dirigido leem os arquivos marcados nele
    scenario = os.environ.get("FAKE_SCENARIO", "discovery_ok")
    marcados = re.findall(r"^### ARQUIVO: (.+)$", prompt, flags=re.M)
    emit({"type": "system", "subtype": "init", "session_id": "sess-fake-1"})
    emit(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Read"}]},
            "session_id": "sess-fake-1",
        }
    )

    if scenario == "limit":
        sys.stderr.write("Session limit reached. Your limit will reset at 3pm.\n")
        return 1
    if scenario == "auth":
        result_event(is_error=True, text="Not logged in · Please run /login", cost=0.0)
        return 1
    if scenario == "rescue":
        if "--resume" in sys.argv:
            result_event(structured={"ok": True}, cost=0.2)
        else:
            result_event(
                is_error=True,
                subtype="error_max_structured_output_retries",
                text="",
                cost=0.5,
            )
        return 0
    if scenario == "inventory_ok":
        cap = os.environ.get("FAKE_CAP", "billing")
        result_event(
            structured={
                "files": [
                    {
                        "path": p,
                        "summary": f"Arquivo {p} trata de cobrança e juros" if "util" not in p
                        else "Utilitário genérico de log",
                        "capabilities": [] if "util" in p else [{"slug": cap, "relevance": 3}]
                        + ([{"slug": "slug-inexistente", "relevance": 2}]
                           if p.endswith("_test.go") else []),
                    }
                    for p in marcados
                ]
                + [{"path": "fantasma.go", "summary": "não estava no lote", "capabilities": []}],
                "suggested_capabilities": [
                    {
                        "name": "Cobrança de Juros",
                        "rationale": "cálculo de juros aparece em vários arquivos",
                        "example_files": marcados[:1],
                    }
                ],
            }
        )
        return 0
    if scenario == "directed_ok":
        alvo = marcados[0] if marcados else "billing.go"
        ini, fim = (int(x) for x in os.environ.get("FAKE_LINES", "3-6").split("-"))
        result_event(
            structured={
                "candidates": [
                    {
                        "kind": "rule",
                        "title": f"Regra dirigida em {alvo}",
                        "statement": f"Regra de negócio extraída de {alvo} nas linhas {ini}-{fim}.",
                        "classification": "OBSERVED_BEHAVIOR",
                        "risk": "LOW",
                        "evidence": [
                            {"file": alvo, "start_line": ini, "end_line": fim,
                             "summary": "trecho lido no turno dirigido"}
                        ],
                    }
                ],
                "questions": [],
                "followups": [
                    {"file": os.environ.get("FAKE_FOLLOWUP", "billing_test.go"),
                     "reason": "testes da regra"},
                    {"file": alvo, "reason": "o próprio alvo (deve ser ignorado)"},
                    {"file": "nao_existe.pas", "reason": "caminho inventado"},
                ],
            }
        )
        return 0
    if scenario == "corrob_ok":
        atom_id = os.environ.get("FAKE_ATOM_ID", "X.Y.RULE.0001")
        result_event(
            structured={
                "findings": [
                    {
                        "atom_id": atom_id,
                        "verdict": "SUPPORTS",
                        "evidence": [
                            {
                                "file": "billing_test.go",
                                "start_line": 2,
                                "end_line": 4,
                                "summary": "Teste confirma o comportamento de juros",
                            }
                        ],
                    }
                ]
            }
        )
        return 0

    # discovery_ok — o texto menciona deliberadamente os termos de franquia para
    # garantir que um resultado BEM-SUCEDIDO nunca vire falso positivo de limite
    result_event(
        text="Análise ok. O legado detecta 'session limit' e 'usage limit' com 'reset'.",
        structured={
            "candidates": [
                {
                    "kind": "rule",
                    "title": "Boleto vencido acumula juros diários",
                    "statement": "Um boleto vencido acumula juros de 1% ao dia sobre o valor.",
                    "classification": "OBSERVED_BEHAVIOR",
                    "risk": "MEDIUM",
                    "evidence": [
                        {
                            "file": "billing.go",
                            "start_line": 3,
                            "end_line": 6,
                            "summary": "Cálculo de juros aplicado após o vencimento",
                        }
                    ],
                },
                {
                    "kind": "rule",
                    "title": "Regra com citação inventada",
                    "statement": "Afirmação com evidência que não existe no repositório.",
                    "classification": "OBSERVED_BEHAVIOR",
                    "evidence": [
                        {
                            "file": "arquivo_inexistente.go",
                            "start_line": 10,
                            "end_line": 20,
                            "summary": "citação alucinada",
                        }
                    ],
                },
                {
                    "kind": "rule",
                    "title": "Duplicata exata da primeira regra",
                    "statement": "Um boleto vencido acumula juros de 1% ao dia sobre o valor.",
                    "classification": "OBSERVED_BEHAVIOR",
                    "evidence": [
                        {
                            "file": "billing.go",
                            "start_line": 3,
                            "end_line": 6,
                            "summary": "mesma evidência",
                        }
                    ],
                },
            ],
            "questions": [
                {
                    "question": "Juros também se aplicam a boletos cancelados?",
                    "context": "billing.go não trata o caso de cancelamento",
                }
            ],
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
