"""Semantic Linter (PRD §60).

Opera sobre uma coleção de atoms/relations/evidence-links para poder ser usado
tanto contra o banco (endpoint) quanto contra o canonical-repo exportado
(`semantic compile`, Fase 2). Cada achado: {code, severity, atom_id, message}.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.kernel.ir.envelope import (
    AtomKind,
    EvidenceRelation,
    LifecycleStatus,
    RelationType,
)
from app.models.knowledge import AtomRelation, EvidenceLink, KnowledgeAtom

ERROR = "error"
WARNING = "warning"

RULE_WITHOUT_EVIDENCE = "RULE_WITHOUT_EVIDENCE"
RULE_WITHOUT_SCOPE = "RULE_WITHOUT_SCOPE"
BROKEN_REFERENCE = "BROKEN_REFERENCE"
CIRCULAR_RELATION = "CIRCULAR_RELATION"
DUPLICATE_ID = "DUPLICATE_ID"
INVALID_TRANSITION = "INVALID_TRANSITION"
CONFLICTING_CANONICAL = "CONFLICTING_CANONICAL"
ORPHAN_ATOM = "ORPHAN_ATOM"
MISSING_CAPABILITY = "MISSING_CAPABILITY"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    atom_id: str
    message: str

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "atom_id": self.atom_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class AtomView:
    """Projeção mínima de um atom para o linter (independente de ORM)."""

    id: str
    kind: str
    status: str
    capability: str | None
    scope: dict | None
    body: dict


@dataclass(frozen=True)
class RelationView:
    from_atom: str
    to_atom: str
    type: str


def _body_references(atom: AtomView) -> list[str]:
    """Atom IDs referenciados dentro do body, por kind."""
    refs: list[str] = []
    if atom.kind == AtomKind.TRANSITION:
        refs.append(atom.body.get("from_state", ""))
        refs.append(atom.body.get("to_state", ""))
        refs.extend(atom.body.get("conditions", []))
    elif atom.kind == AtomKind.EXCEPTION:
        refs.append(atom.body.get("applies_to", ""))
    return [r for r in refs if r]


def lint(
    atoms: list[AtomView],
    relations: list[RelationView],
    supported_atom_ids: set[str],
) -> list[Finding]:
    """supported_atom_ids: atoms com >= 1 evidence link de suporte."""
    findings: list[Finding] = []
    ids = [a.id for a in atoms]
    by_id = {a.id: a for a in atoms}

    # DUPLICATE_ID — impossível no banco (PK), relevante para coleções compiladas
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            findings.append(Finding(DUPLICATE_ID, ERROR, i, f"ID duplicado: {i}"))
        seen.add(i)

    related_ids: set[str] = set()
    for r in relations:
        related_ids.add(r.from_atom)
        related_ids.add(r.to_atom)
        for endpoint in (r.from_atom, r.to_atom):
            if endpoint not in by_id:
                findings.append(
                    Finding(
                        BROKEN_REFERENCE,
                        ERROR,
                        endpoint,
                        f"Relação {r.type} referencia atom inexistente: {endpoint}",
                    )
                )

    for atom in atoms:
        if atom.kind == AtomKind.RULE:
            if atom.id not in supported_atom_ids:
                findings.append(
                    Finding(
                        RULE_WITHOUT_EVIDENCE,
                        ERROR,
                        atom.id,
                        "Rule sem evidence de suporte (P5)",
                    )
                )
            if not atom.scope:
                findings.append(
                    Finding(RULE_WITHOUT_SCOPE, WARNING, atom.id, "Rule sem scope definido")
                )

        if atom.capability is None:
            findings.append(
                Finding(MISSING_CAPABILITY, WARNING, atom.id, "Atom sem capability")
            )

        for ref in _body_references(atom):
            if ref not in by_id:
                findings.append(
                    Finding(
                        BROKEN_REFERENCE,
                        ERROR,
                        atom.id,
                        f"Body referencia atom inexistente: {ref}",
                    )
                )

        if atom.kind == AtomKind.TRANSITION:
            for endpoint_field in ("from_state", "to_state"):
                ref = atom.body.get(endpoint_field, "")
                target = by_id.get(ref)
                if target is not None and target.kind != AtomKind.STATE:
                    findings.append(
                        Finding(
                            INVALID_TRANSITION,
                            ERROR,
                            atom.id,
                            f"{endpoint_field} ({ref}) não é um atom de kind state",
                        )
                    )

        if (
            atom.id not in related_ids
            and not _body_references(atom)
            and atom.id not in supported_atom_ids
        ):
            findings.append(
                Finding(ORPHAN_ATOM, WARNING, atom.id, "Atom sem relações nem evidence")
            )

    # CONFLICTING_CANONICAL: CONTRADICTS entre dois atoms CANONICAL (§60)
    for r in relations:
        if r.type != RelationType.CONTRADICTS:
            continue
        a, b = by_id.get(r.from_atom), by_id.get(r.to_atom)
        if (
            a is not None
            and b is not None
            and a.status == LifecycleStatus.CANONICAL
            and b.status == LifecycleStatus.CANONICAL
        ):
            findings.append(
                Finding(
                    CONFLICTING_CANONICAL,
                    ERROR,
                    a.id,
                    f"Regras canonical em contradição: {a.id} × {b.id}",
                )
            )

    # CIRCULAR_RELATION: ciclos em DEPENDS_ON
    graph: dict[str, list[str]] = {}
    for r in relations:
        if r.type == RelationType.DEPENDS_ON:
            graph.setdefault(r.from_atom, []).append(r.to_atom)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = dict.fromkeys(graph, WHITE)

    def visit(node: str, path: list[str]) -> None:
        color[node] = GRAY
        for nxt in graph.get(node, []):
            if color.get(nxt, WHITE) == GRAY:
                ciclo = path[path.index(nxt):] + [nxt] if nxt in path else [node, nxt]
                findings.append(
                    Finding(
                        CIRCULAR_RELATION,
                        ERROR,
                        nxt,
                        "Ciclo em DEPENDS_ON: " + " → ".join(ciclo),
                    )
                )
            elif color.get(nxt, WHITE) == WHITE and nxt in graph:
                visit(nxt, path + [nxt])
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            visit(node, [node])

    return findings


def lint_db(db: Session) -> list[Finding]:
    """Executa o linter sobre o estado atual do banco."""
    atoms = [
        AtomView(
            id=a.id,
            kind=a.kind,
            status=a.status,
            capability=a.capability,
            scope=a.scope,
            body=a.body or {},
        )
        for a in db.scalars(select(KnowledgeAtom))
    ]
    relations = [
        RelationView(from_atom=r.from_atom, to_atom=r.to_atom, type=r.type)
        for r in db.scalars(select(AtomRelation))
    ]
    supported = {
        link.atom_id
        for link in db.scalars(
            select(EvidenceLink).where(EvidenceLink.relation == str(EvidenceRelation.SUPPORTS))
        )
    }
    return lint(atoms, relations, supported)
