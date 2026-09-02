"""Linter §60 — cada violação da lista deve ser acusada (critério de saída Fase 1)."""

from app.kernel import linter
from app.kernel.linter import AtomView, Finding, RelationView, lint


def _atom(id, kind="rule", status="CANDIDATE", capability="ar", scope=None, body=None):
    return AtomView(
        id=id, kind=kind, status=status, capability=capability, scope=scope, body=body or {}
    )


def _codes(findings: list[Finding]) -> set[str]:
    return {f.code for f in findings}


def test_rule_sem_evidence_e_sem_scope():
    atoms = [_atom("F.AR.RULE.0001", scope=None)]
    findings = lint(atoms, [], supported_atom_ids=set())
    assert linter.RULE_WITHOUT_EVIDENCE in _codes(findings)
    assert linter.RULE_WITHOUT_SCOPE in _codes(findings)


def test_rule_com_evidence_e_scope_passa():
    atoms = [_atom("F.AR.RULE.0001", scope={"country": "BR"})]
    findings = lint(atoms, [], supported_atom_ids={"F.AR.RULE.0001"})
    assert linter.RULE_WITHOUT_EVIDENCE not in _codes(findings)
    assert linter.RULE_WITHOUT_SCOPE not in _codes(findings)


def test_broken_reference_no_body():
    atoms = [
        _atom(
            "F.AR.EXCEPTION.0001",
            kind="exception",
            body={"applies_to": "F.AR.RULE.NAO-EXISTE", "condition": "x"},
        )
    ]
    findings = lint(atoms, [], supported_atom_ids=set())
    assert linter.BROKEN_REFERENCE in _codes(findings)


def test_broken_reference_em_relacao():
    atoms = [_atom("A.B.CONCEPT.0001", kind="concept")]
    rels = [RelationView("A.B.CONCEPT.0001", "A.B.FANTASMA.0001", "DEPENDS_ON")]
    findings = lint(atoms, rels, supported_atom_ids=set())
    assert linter.BROKEN_REFERENCE in _codes(findings)


def test_ciclo_em_depends_on():
    atoms = [_atom(f"A.B.RULE.{i}", scope={"s": 1}) for i in ("0001", "0002", "0003")]
    rels = [
        RelationView("A.B.RULE.0001", "A.B.RULE.0002", "DEPENDS_ON"),
        RelationView("A.B.RULE.0002", "A.B.RULE.0003", "DEPENDS_ON"),
        RelationView("A.B.RULE.0003", "A.B.RULE.0001", "DEPENDS_ON"),
    ]
    findings = lint(atoms, rels, supported_atom_ids={a.id for a in atoms})
    assert linter.CIRCULAR_RELATION in _codes(findings)


def test_duplicate_id_em_colecao():
    atoms = [_atom("A.B.RULE.0001"), _atom("A.B.RULE.0001")]
    findings = lint(atoms, [], supported_atom_ids=set())
    assert linter.DUPLICATE_ID in _codes(findings)


def test_transition_para_nao_state():
    atoms = [
        _atom("A.B.STATE.ISSUED", kind="state"),
        _atom("A.B.RULE.0001", scope={"s": 1}),
        _atom(
            "A.B.TRANSITION.0001",
            kind="transition",
            body={"from_state": "A.B.STATE.ISSUED", "to_state": "A.B.RULE.0001"},
        ),
    ]
    findings = lint(atoms, [], supported_atom_ids={"A.B.RULE.0001"})
    assert linter.INVALID_TRANSITION in _codes(findings)


def test_conflicting_canonical():
    atoms = [
        _atom("A.B.RULE.0001", status="CANONICAL", scope={"s": 1}),
        _atom("A.B.RULE.0002", status="CANONICAL", scope={"s": 1}),
    ]
    rels = [RelationView("A.B.RULE.0001", "A.B.RULE.0002", "CONTRADICTS")]
    findings = lint(atoms, rels, supported_atom_ids={a.id for a in atoms})
    assert linter.CONFLICTING_CANONICAL in _codes(findings)


def test_orphan_e_missing_capability_sao_warnings():
    atoms = [_atom("A.B.CONCEPT.0001", kind="concept", capability=None)]
    findings = lint(atoms, [], supported_atom_ids=set())
    by_code = {f.code: f for f in findings}
    assert by_code[linter.ORPHAN_ATOM].severity == "warning"
    assert by_code[linter.MISSING_CAPABILITY].severity == "warning"
