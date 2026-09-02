"""Projection Engine (PRD §64-§68): BDD/Gherkin, decision tables, state machine, markdown.

Projeções são derivadas do IR — nunca fonte da verdade.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.kernel.errors import KernelError
from app.kernel.ir.envelope import AtomKind, LifecycleStatus
from app.models.knowledge import KnowledgeAtom
from app.services import context as ctx


def _texto(valor) -> str:
    if isinstance(valor, dict):
        return valor.get("description") or ", ".join(
            f"{k}={v}" for k, v in valor.items() if k != "description"
        )
    return str(valor or "")


def gherkin_for_scenario(atom: KnowledgeAtom) -> str:
    """§65: Scenario → Gherkin."""
    if atom.kind != str(AtomKind.SCENARIO):
        raise KernelError(f"{atom.id} não é um scenario")
    body = atom.body or {}
    return "\n".join(
        [
            f"Scenario: {atom.title}",
            f"  Given {_texto(body.get('given')) or '—'}",
            f"  When {_texto(body.get('when')) or '—'}",
            f"  Then {_texto(body.get('then')) or '—'}",
        ]
    )


def feature_for_capability(
    db: Session, capability: str, *, canonical_only: bool = True
) -> str:
    stmt = select(KnowledgeAtom).where(
        KnowledgeAtom.capability == capability,
        KnowledgeAtom.kind == str(AtomKind.SCENARIO),
    )
    if canonical_only:
        stmt = stmt.where(KnowledgeAtom.status == str(LifecycleStatus.CANONICAL))
    cenarios = list(db.scalars(stmt.order_by(KnowledgeAtom.id)))
    linhas = [f"Feature: {capability}", ""]
    if not cenarios:
        linhas.append("  # Nenhum scenario" + (" canonical" if canonical_only else ""))
    for s in cenarios:
        marca = "" if s.status == str(LifecycleStatus.CANONICAL) else "  # [OBSERVED]\n"
        linhas.append(marca + "\n".join("  " + ln for ln in gherkin_for_scenario(s).splitlines()))
        linhas.append("")
    return "\n".join(linhas)


def decision_table(atom: KnowledgeAtom) -> dict:
    """§66: Decision → visão tabular (linhas vêm de body.logic.rows quando existirem)."""
    if atom.kind != str(AtomKind.DECISION):
        raise KernelError(f"{atom.id} não é uma decision")
    body = atom.body or {}
    logic = body.get("logic") or {}
    return {
        "id": atom.id,
        "title": atom.title,
        "inputs": body.get("inputs", []),
        "output": body.get("output"),
        "type": logic.get("type", "decision_table"),
        "rows": logic.get("rows", []),  # [{<input>: cond, ..., "output": valor}]
        "status": atom.status,
    }


def state_machine(db: Session, capability: str) -> dict:
    """§67: states + transitions da capability, prontos para render."""
    atoms = list(
        db.scalars(
            select(KnowledgeAtom).where(
                KnowledgeAtom.capability == capability,
                KnowledgeAtom.kind.in_([str(AtomKind.STATE), str(AtomKind.TRANSITION)]),
            )
        )
    )
    states = [
        {"id": a.id, "title": a.title, "status": a.status, "order": (a.body or {}).get("order")}
        for a in atoms
        if a.kind == str(AtomKind.STATE)
    ]
    ids_state = {s["id"]: s["title"] for s in states}
    transitions = []
    for a in atoms:
        if a.kind != str(AtomKind.TRANSITION):
            continue
        body = a.body or {}
        transitions.append(
            {
                "id": a.id,
                "from": body.get("from_state"),
                "from_title": ids_state.get(body.get("from_state")),
                "to": body.get("to_state"),
                "to_title": ids_state.get(body.get("to_state")),
                "trigger": body.get("trigger"),
                "conditions": body.get("conditions", []),
                "status": a.status,
            }
        )
    return {"capability": capability, "states": states, "transitions": transitions}


def markdown_doc(db: Session, capability: str) -> str:
    """§64: documentação markdown canonical da capability (projeção do Context Builder)."""
    return ctx.to_markdown(ctx.build_package(db, capability=capability))
