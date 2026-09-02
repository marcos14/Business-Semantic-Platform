"""Conflict Resolution Workspace (PRD §48-§50, §74).

Conflitos são conhecimento (P7): nunca são removidos nem auto-merged. O sistema
detecta e registra; a escolha é sempre humana (Decision Owner, AC-CON-03).
"""

import enum
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.kernel import events
from app.kernel.errors import KernelError, NotFoundError
from app.kernel.ir.envelope import (
    AtomKind,
    Classification,
    EvidenceRelation,
    EvidenceType,
    LifecycleStatus,
    Origin,
    RelationType,
)
from app.llm import provider as llm
from app.models.auth import User
from app.models.knowledge import AtomRelation, EvidenceLink, KnowledgeAtom
from app.services import knowledge as ksvc

SYSTEM_ACTOR = "system:conflict-detection"

# Status em que um atom pode ser movido para CONFLICTED automaticamente
# (canonical NUNCA muda sozinho — §74)
_MOVABLE = {
    str(s)
    for s in (
        LifecycleStatus.CANDIDATE,
        LifecycleStatus.CORROBORATING,
        LifecycleStatus.READY_FOR_EVALUATION,
        LifecycleStatus.NEEDS_HUMAN_REVIEW,
        LifecycleStatus.IN_REVIEW,
        LifecycleStatus.DECISION_PENDING,
    )
}


class ConflictResolution(enum.StrEnum):
    """Ações do §50 (split by time entra junto com scope; DMN/BPMN fora do MVP)."""

    SELECT_ASSERTION = "SELECT_ASSERTION"
    NEW_INTERPRETATION = "NEW_INTERPRETATION"
    SPLIT_BY_SCOPE = "SPLIT_BY_SCOPE"
    SPLIT_BY_TIME = "SPLIT_BY_TIME"
    MARK_LEGACY_BUG = "MARK_LEGACY_BUG"
    MARK_UNRESOLVED = "MARK_UNRESOLVED"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"


def _open_conflicts(db: Session, domain: str | None = None) -> list[KnowledgeAtom]:
    stmt = select(KnowledgeAtom).where(
        KnowledgeAtom.kind == str(AtomKind.CONFLICT),
        KnowledgeAtom.body["state"].astext == "open",
    )
    if domain:
        stmt = stmt.where(KnowledgeAtom.domain == domain)
    return list(db.scalars(stmt))


def _atoms_of(conflict: KnowledgeAtom) -> list[str]:
    body = conflict.body or {}
    if body.get("about"):
        return [body["about"]]
    return [a["atom_id"] for a in body.get("assertions", []) if a.get("atom_id")]


def _create_conflict(
    db: Session,
    *,
    actor: str,
    domain: str,
    capability: str | None,
    title: str,
    body: dict,
) -> KnowledgeAtom:
    conflict = ksvc.create_candidate(
        db,
        actor=actor,
        origin=Origin.AGENT if actor.startswith(("agent:", "system:")) else Origin.HUMAN,
        kind=AtomKind.CONFLICT,
        title=title,
        domain=domain,
        capability=capability,
        body=body,
    )
    db.flush()
    # AC-CON-02: conflito É item de revisão — status CONFLICTED entra na Inbox
    conflict = ksvc.change_status(
        db,
        conflict.id,
        actor=actor,
        new_status=LifecycleStatus.CONFLICTED,
        reason="conflito aberto",
        expected_lock_version=conflict.lock_version,
    )
    events.record_event(
        db, events.CONFLICT_DETECTED, actor, conflict.id,
        {"about": body.get("about"), "assertions": body.get("assertions", []),
         "reevaluation": body.get("reevaluation", False)},
    )
    return conflict


def ensure_conflict_for_atom(
    db: Session, atom: KnowledgeAtom, *, actor: str, evidence_id: str, reevaluation: bool
) -> KnowledgeAtom | None:
    """Evidência contraditória encontrada (§48/§74): garante UM conflito aberto por atom."""
    for c in _open_conflicts(db, atom.domain):
        if (c.body or {}).get("about") == atom.id:
            return None  # já existe conflito aberto para este atom
    conflict = _create_conflict(
        db,
        actor=actor,
        domain=atom.domain,
        capability=atom.capability,
        title=f"Evidência contraditória: {atom.title}"[:300],
        body={
            "topic": atom.title,
            "about": atom.id,
            "assertions": [],
            "reevaluation": reevaluation,
            "state": "open",
        },
    )
    ksvc.add_relation(
        db, actor=actor, from_atom=conflict.id, to_atom=atom.id,
        relation_type=RelationType.AFFECTS,
    )
    # AC-CAN-03/§74: canonical permanece intocado; demais vão para CONFLICTED
    if atom.status in _MOVABLE:
        ksvc.change_status(
            db, atom.id, actor=actor, new_status=LifecycleStatus.CONFLICTED,
            reason=f"evidência contraditória (evidence {evidence_id})",
            expected_lock_version=atom.lock_version,
        )
    return conflict


def _pair_conflict_exists(db: Session, domain: str, a: str, b: str) -> bool:
    for c in _open_conflicts(db, domain):
        ids = set(_atoms_of(c))
        if {a, b} <= ids:
            return True
    return False


def create_pair_conflict(
    db: Session, *, actor: str, atom_a: KnowledgeAtom, atom_b: KnowledgeAtom, topic: str
) -> KnowledgeAtom | None:
    if _pair_conflict_exists(db, atom_a.domain, atom_a.id, atom_b.id):
        return None
    conflict = _create_conflict(
        db,
        actor=actor,
        domain=atom_a.domain,
        capability=atom_a.capability,
        title=f"Conflito: {topic}"[:300],
        body={
            "topic": topic,
            "about": None,
            "assertions": [
                {
                    "atom_id": atom_a.id,
                    "statement": (atom_a.body or {}).get("statement") or atom_a.title,
                },
                {
                    "atom_id": atom_b.id,
                    "statement": (atom_b.body or {}).get("statement") or atom_b.title,
                },
            ],
            "state": "open",
        },
    )
    for alvo in (atom_a, atom_b):
        ksvc.add_relation(
            db, actor=actor, from_atom=conflict.id, to_atom=alvo.id,
            relation_type=RelationType.AFFECTS,
        )
        if alvo.status in _MOVABLE:
            ksvc.change_status(
                db, alvo.id, actor=actor, new_status=LifecycleStatus.CONFLICTED,
                reason=f"conflito com {atom_b.id if alvo is atom_a else atom_a.id}",
                expected_lock_version=alvo.lock_version,
            )
    return conflict


def detect_conflicts(db: Session, *, domain: str, capability: str | None, actor: str) -> list[str]:
    """Detecção determinística: evidência contraditória + relações CONTRADICTS."""
    criados: list[str] = []
    stmt = select(KnowledgeAtom).where(
        KnowledgeAtom.domain == domain, KnowledgeAtom.kind != str(AtomKind.CONFLICT)
    )
    if capability:
        stmt = stmt.where(KnowledgeAtom.capability == capability)
    atoms = {a.id: a for a in db.scalars(stmt)}

    # 1. atoms com evidência contraditória
    contras = set(
        db.scalars(
            select(EvidenceLink.atom_id).where(
                EvidenceLink.atom_id.in_(atoms),
                EvidenceLink.relation == str(EvidenceRelation.CONTRADICTS),
            )
        )
    )
    for atom_id in sorted(contras):
        c = ensure_conflict_for_atom(
            db, atoms[atom_id], actor=actor, evidence_id="varredura",
            reevaluation=atoms[atom_id].status == str(LifecycleStatus.CANONICAL),
        )
        if c:
            criados.append(c.id)

    # 2. pares ligados por CONTRADICTS
    rels = db.scalars(
        select(AtomRelation).where(
            AtomRelation.type == str(RelationType.CONTRADICTS),
            AtomRelation.from_atom.in_(atoms),
            AtomRelation.to_atom.in_(atoms),
        )
    )
    for r in rels:
        c = create_pair_conflict(
            db, actor=actor, atom_a=atoms[r.from_atom], atom_b=atoms[r.to_atom],
            topic=f"{atoms[r.from_atom].title} × {atoms[r.to_atom].title}",
        )
        if c:
            criados.append(c.id)
    return criados


_LLM_DETECT_SYSTEM = (
    "Você compara afirmações de negócio candidatas e aponta APENAS pares realmente "
    "incompatíveis (não podem ser ambas verdadeiras no mesmo escopo). Responda SOMENTE "
    'JSON: {"pairs": [{"a": "<id>", "b": "<id>", "topic": "<resumo do desacordo>"}]}. '
    "Sem pares: lista vazia. Nunca invente ids."
)


def detect_conflicts_llm(
    db: Session,
    *,
    domain: str,
    capability: str | None,
    actor: str,
    llm_provider: llm.LLMProvider | None = None,
    max_atoms: int = 40,
) -> list[str]:
    """Conflict Detection Agent (§11) via porta LLMProvider: contradições semânticas."""
    stmt = select(KnowledgeAtom).where(
        KnowledgeAtom.domain == domain,
        KnowledgeAtom.kind.in_(["rule", "invariant"]),
    )
    if capability:
        stmt = stmt.where(KnowledgeAtom.capability == capability)
    atoms = {a.id: a for a in db.scalars(stmt.limit(max_atoms))}
    if len(atoms) < 2:
        return []
    listagem = "\n".join(
        f"- {a.id}: {(a.body or {}).get('statement') or a.title}" for a in atoms.values()
    )
    resposta = (llm_provider or llm.get_provider()).complete(
        system=_LLM_DETECT_SYSTEM, user=listagem, max_tokens=2000
    )
    ini, fim = resposta.find("{"), resposta.rfind("}")
    if ini < 0 or fim <= ini:
        raise KernelError("Detector LLM não devolveu JSON reconhecível")
    pares = json.loads(resposta[ini : fim + 1]).get("pairs", [])
    criados: list[str] = []
    for p in pares:
        a, b = atoms.get(p.get("a")), atoms.get(p.get("b"))
        if a is None or b is None or a.id == b.id:
            continue  # id inventado é descartado (P5)
        c = create_pair_conflict(
            db, actor=actor, atom_a=a, atom_b=b, topic=p.get("topic") or f"{a.title} × {b.title}"
        )
        if c:
            criados.append(c.id)
    return criados


def _walk_to_decision(db: Session, atom_id: str, actor: str, reason: str) -> None:
    atom = ksvc.get_atom(db, atom_id)
    if atom.status == str(LifecycleStatus.CONFLICTED):
        atom = ksvc.change_status(
            db, atom_id, actor=actor, new_status=LifecycleStatus.IN_REVIEW,
            reason=reason, expected_lock_version=atom.lock_version,
        )
    if atom.status == str(LifecycleStatus.IN_REVIEW):
        ksvc.change_status(
            db, atom_id, actor=actor, new_status=LifecycleStatus.DECISION_PENDING,
            reason=reason, expected_lock_version=atom.lock_version,
        )


def resolve_conflict(
    db: Session,
    conflict_id: str,
    owner: User,
    *,
    action: ConflictResolution,
    reason: str,
    expected_lock_version: int,
    params: dict | None = None,
) -> KnowledgeAtom:
    """Resolução do owner (§50, AC-CON-03). NUNCA muda atoms CANONICAL — para esses,
    o caminho é new-version/supersede (§71-§72)."""
    params = params or {}
    conflict = ksvc.get_atom(db, conflict_id)
    if conflict.kind != str(AtomKind.CONFLICT):
        raise KernelError(f"{conflict_id} não é um conflict")
    if (conflict.body or {}).get("state") != "open":
        raise KernelError("Conflito já foi resolvido/encerrado")
    if conflict.lock_version != expected_lock_version:
        from app.kernel.errors import StaleVersionError

        # §105: dois owners resolvendo o mesmo conflito → o segundo recebe 409
        raise StaleVersionError(
            f"Versão desatualizada: esperada {expected_lock_version}, "
            f"atual {conflict.lock_version}"
        )
    afetados = [ksvc.get_atom(db, aid) for aid in _atoms_of(conflict)]
    canonicos = [a.id for a in afetados if a.status == str(LifecycleStatus.CANONICAL)]

    def _exigir_nao_canonico():
        if canonicos:
            raise KernelError(
                f"Atoms canonical ({canonicos}) não mudam por resolução de conflito: "
                "use new-version ou supersede (§71-§74)"
            )

    match action:
        case ConflictResolution.SELECT_ASSERTION:
            winner = params.get("winner_atom_id")
            if winner not in {a.id for a in afetados}:
                raise NotFoundError(f"winner_atom_id inválido: {winner}")
            _exigir_nao_canonico()
            for a in afetados:
                if a.id == winner:
                    _walk_to_decision(db, a.id, owner.email, f"assertion vencedora: {reason}")
                else:
                    ksvc.change_status(
                        db, a.id, actor=owner.email, new_status=LifecycleStatus.REJECTED,
                        reason=f"assertion perdedora do conflito {conflict_id}: {reason}",
                        expected_lock_version=a.lock_version,
                    )
        case ConflictResolution.SPLIT_BY_SCOPE | ConflictResolution.SPLIT_BY_TIME:
            campo = "scope" if action == ConflictResolution.SPLIT_BY_SCOPE else "effective"
            splits = params.get("splits") or []
            ids_afetados = {a.id for a in afetados}
            if not splits or any(s.get("atom_id") not in ids_afetados for s in splits):
                raise KernelError(f"splits deve cobrir atoms do conflito com {campo}")
            _exigir_nao_canonico()
            for s in splits:
                atom = ksvc.get_atom(db, s["atom_id"])
                ksvc.update_atom(
                    db, atom.id, actor=owner.email,
                    expected_lock_version=atom.lock_version,
                    changes={campo: s[campo]},
                )
                _walk_to_decision(db, atom.id, owner.email, f"split por {campo}: {reason}")
        case ConflictResolution.NEW_INTERPRETATION:
            if not params.get("title") or not params.get("statement"):
                raise KernelError("NEW_INTERPRETATION exige {title, statement}")
            _exigir_nao_canonico()
            nova = ksvc.create_candidate(
                db, actor=owner.email, origin=Origin.HUMAN, kind=AtomKind.RULE,
                title=params["title"], domain=conflict.domain,
                capability=conflict.capability, scope=params.get("scope"),
                body={"statement": params["statement"]},
                evidence=[{
                    "type": EvidenceType.HUMAN_REVIEW,
                    "summary": f"Interpretação definida pelo owner ao resolver {conflict_id}",
                    "metadata": {"reviewer": owner.email, "decision": "NEW_INTERPRETATION"},
                }],
            )
            db.flush()
            for a in afetados:
                ksvc.change_status(
                    db, a.id, actor=owner.email, new_status=LifecycleStatus.REJECTED,
                    reason=f"substituída pela interpretação {nova.id}: {reason}",
                    expected_lock_version=a.lock_version,
                )
                ksvc.add_relation(
                    db, actor=owner.email, from_atom=nova.id, to_atom=a.id,
                    relation_type=RelationType.SUPERSEDES,
                )
        case ConflictResolution.MARK_LEGACY_BUG:
            alvo = params.get("atom_id")
            if alvo not in {a.id for a in afetados}:
                raise NotFoundError(f"atom_id inválido: {alvo}")
            _exigir_nao_canonico()
            atom = ksvc.get_atom(db, alvo)
            atom = ksvc.update_atom(
                db, alvo, actor=owner.email, expected_lock_version=atom.lock_version,
                changes={"classification": Classification.KNOWN_BUG},
            )
            ksvc.change_status(
                db, alvo, actor=owner.email, new_status=LifecycleStatus.LEGACY_BUG,
                reason=reason, expected_lock_version=atom.lock_version,
            )
        case ConflictResolution.REQUEST_EVIDENCE:
            for a in afetados:
                if a.status in _MOVABLE or a.status == str(LifecycleStatus.CONFLICTED):
                    ksvc.change_status(
                        db, a.id, actor=owner.email,
                        new_status=LifecycleStatus.CORROBORATING,
                        reason=f"mais evidência para o conflito: {reason}",
                        expected_lock_version=a.lock_version,
                    )
        case ConflictResolution.MARK_UNRESOLVED:
            pass  # apenas o estado do conflito muda (P7: nada é escondido)
        case _:
            raise KernelError(f"Ação de resolução desconhecida: {action}")

    novo_estado = "unresolved" if action == ConflictResolution.MARK_UNRESOLVED else "resolved"
    conflict = ksvc.get_atom(db, conflict_id)
    conflict = ksvc.update_atom(
        db, conflict_id, actor=owner.email,
        expected_lock_version=conflict.lock_version,
        changes={
            "body": {
                **conflict.body,
                "state": novo_estado,
                "resolution": {"action": str(action), "by": owner.email, "reason": reason},
            }
        },
    )
    events.record_event(
        db, events.DECISION_MADE, owner.email, conflict_id,
        {"conflict_resolution": str(action), "reason": reason, "state": novo_estado},
    )
    return conflict
