import pytest
from pydantic import BaseModel

from app.kernel.errors import BodyValidationError
from app.kernel.ir.envelope import AtomKind, validate_atom_id
from app.kernel.ir.registry import known_kinds, register, validate_body


def test_todos_os_kinds_do_prd_registrados():
    # PRD §13 (Evidence é entidade própria, não kind)
    assert set(known_kinds()) >= {
        "concept",
        "rule",
        "decision",
        "invariant",
        "state",
        "transition",
        "event",
        "process",
        "scenario",
        "exception",
        "conflict",
        "question",
        "capability",
    }


def test_rule_exige_statement():
    with pytest.raises(BodyValidationError):
        validate_body(AtomKind.RULE, {})
    body = validate_body(AtomKind.RULE, {"statement": "Cancelled invoice cannot receive payment"})
    assert body["statement"].startswith("Cancelled")


def test_campo_desconhecido_e_erro():
    with pytest.raises(BodyValidationError):
        validate_body(AtomKind.CONCEPT, {"campo_inventado": 1})


def test_kind_desconhecido():
    with pytest.raises(BodyValidationError):
        validate_body("tipo_novo", {})


def test_extensibilidade_novo_kind_sem_migracao():
    class MetricBody(BaseModel):
        formula: str

    register("metric", MetricBody)
    assert validate_body("metric", {"formula": "a/b"}) == {"formula": "a/b"}


def test_decision_exige_inputs_e_output():
    with pytest.raises(BodyValidationError):
        validate_body(AtomKind.DECISION, {"inputs": [], "output": "x"})
    ok = validate_body(
        AtomKind.DECISION,
        {"inputs": ["customer.risk_level"], "output": "approval_required"},
    )
    assert ok["logic"] is None


def test_validacao_de_atom_id():
    validate_atom_id("FINANCE.ACCOUNTS-RECEIVABLE.RULE.0012")
    with pytest.raises(ValueError):
        validate_atom_id("finance.rule.1")  # minúsculas
    with pytest.raises(ValueError):
        validate_atom_id("SOSEGMENTO")  # sem separador
