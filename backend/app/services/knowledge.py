"""Serviços de domínio do kernel — a ÚNICA porta de escrita de Knowledge Atoms.

Toda mutação: valida (registry + lifecycle + gates), grava snapshot imutável e
emite domain events na MESMA transação (D2/D4 da arquitetura). O commit é do
chamador (router/job), garantindo atomicidade estado+eventos.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.kernel import events, lifecycle
from app.kernel.errors import (
    AuthorityError,
    DuplicateError,
    EvidenceRequiredError,
    KernelError,
    NotFoundError,
    StaleVersionError,
)
from app.kernel.ir.envelope import (
    AtomKind,
    Classification,
    EvidenceRelation,
    EvidenceType,
    LifecycleStatus,
    Origin,
    RelationType,
    RiskLevel,
    id_prefix,
    validate_atom_id,
)
from app.kernel.ir.registry import validate_body
from app.models.auth import Capability, Domain
from app.models.knowledge import (
    AtomRelation,
    DomainEvent,
    Evidence,
    EvidenceLink,
    KnowledgeAtom,
    KnowledgeAtomVersion,
    Source,
)

# Campos do envelope editáveis via update_atom (status NUNCA por aqui)
MUTABLE_FIELDS = {"title", "description", "classification", "risk", "scope", "effective", "body"}


def _snapshot(db: Session, atom: KnowledgeAtom, actor: str) -> None:
    db.add(
        KnowledgeAtomVersion(
            atom_id=atom.id,
            rev=atom.lock_version,
            version=atom.version,
            created_by=actor,
            snapshot={
                "id": atom.id,
                "kind": atom.kind,
                "title": atom.title,
                "description": atom.description,
                "domain": atom.domain,
                "capability": atom.capability,
                "status": atom.status,
                "classification": atom.classification,
                "confidence": atom.confidence,
                "risk": atom.risk,
                "scope": atom.scope,
                "effective": atom.effective,
                "body": atom.body,
                "origin": atom.origin,
                "version": atom.version,
                "created_by": atom.created_by,
            },
        )
    )


def _check_lock(atom: KnowledgeAtom, expected_lock_version: int) -> None:
    if atom.lock_version != expected_lock_version:
        raise StaleVersionError(
            f"Versão desatualizada: esperada {expected_lock_version}, "
            f"atual {atom.lock_version}. Recarregue o atom (§105)."
        )


def get_atom(db: Session, atom_id: str) -> KnowledgeAtom:
    atom = db.get(KnowledgeAtom, atom_id)
    if atom is None:
        raise NotFoundError(f"Atom não encontrado: {atom_id}")
    return atom


def generate_atom_id(db: Session, domain: str, capability: str | None, kind: AtomKind) -> str:
    prefix = id_prefix(domain, capability, kind)
    n = db.scalar(
        select(func.count()).select_from(KnowledgeAtom).where(KnowledgeAtom.id.like(prefix + ".%"))
    )
    return f"{prefix}.{(n or 0) + 1:04d}"


def _validate_scope_refs(db: Session, domain: str, capability: str | None) -> None:
    if db.get(Domain, domain) is None:
        raise NotFoundError(f"Domain inexistente: {domain}")
    if capability is not None:
        cap = db.get(Capability, capability)
        if cap is None:
            raise NotFoundError(f"Capability inexistente: {capability}")
        if cap.domain_slug != domain:
            raise KernelError(f"Capability {capability} não pertence ao domain {domain}")


def create_candidate(
    db: Session,
    *,
    actor: str,
    origin: Origin,
    kind: AtomKind,
    title: str,
    domain: str,
    capability: str | None = None,
    description: str | None = None,
    classification: Classification | None = None,
    risk: RiskLevel | None = None,
    scope: dict | None = None,
    effective: dict | None = None,
    body: dict | None = None,
    atom_id: str | None = None,
    initial_status: LifecycleStatus = LifecycleStatus.CANDIDATE,
    evidence: list[dict] | None = None,
) -> KnowledgeAtom:
    """Cria um candidate no Discovery Space.

    Gates do kernel:
    - body validado contra o schema do kind (registry);
    - AC-EVI-01: origin=agent sem evidence é rejeitado;
    - status inicial restrito a DISCOVERED/CANDIDATE.
    """
    if initial_status not in lifecycle.INITIAL_STATUSES:
        raise KernelError(f"Status inicial inválido: {initial_status}")
    evidence = evidence or []
    # P5/AC-EVI-01: afirmação automática exige evidence. Question/Conflict não são
    # afirmações (P6: UNKNOWN é resultado válido) — podem nascer sem evidence.
    if (
        origin == Origin.AGENT
        and not evidence
        and AtomKind(kind) not in (AtomKind.QUESTION, AtomKind.CONFLICT)
    ):
        raise EvidenceRequiredError(
            "Candidate automático sem evidence é rejeitado (P5, AC-EVI-01)"
        )
    _validate_scope_refs(db, domain, capability)
    normalized_body = validate_body(kind, body)

    if atom_id is not None:
        try:
            validate_atom_id(atom_id)
        except ValueError as e:
            raise KernelError(str(e)) from None
        if db.get(KnowledgeAtom, atom_id) is not None:
            raise DuplicateError(f"Atom já existe: {atom_id}")
    else:
        atom_id = generate_atom_id(db, domain, capability, kind)

    atom = KnowledgeAtom(
        id=atom_id,
        kind=str(kind),
        title=title,
        description=description,
        domain=domain,
        capability=capability,
        status=str(initial_status),
        classification=str(classification) if classification else None,
        risk=str(risk) if risk else None,
        scope=scope,
        effective=effective,
        body=normalized_body,
        origin=str(origin),
        created_by=actor,
    )
    db.add(atom)
    db.flush()

    for ev in evidence:
        _add_evidence(db, atom, actor=actor, origin=origin, **ev)

    _snapshot(db, atom, actor)
    events.record_event(
        db,
        events.CANDIDATE_DISCOVERED,
        actor,
        atom.id,
        {"kind": atom.kind, "origin": atom.origin, "status": atom.status, "title": atom.title},
    )
    return atom


def _add_evidence(
    db: Session,
    atom: KnowledgeAtom,
    *,
    actor: str,
    origin: Origin,
    type: EvidenceType,
    source_id: uuid.UUID | None = None,
    location: dict | None = None,
    summary: str | None = None,
    excerpt: str | None = None,
    metadata: dict | None = None,
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
) -> Evidence:
    if source_id is not None and db.get(Source, source_id) is None:
        raise NotFoundError(f"Source inexistente: {source_id}")
    ev = Evidence(
        type=str(EvidenceType(type)),
        source_id=source_id,
        location=location,
        summary=summary,
        excerpt=excerpt,
        meta=metadata,
        origin=str(origin),
        created_by=actor,
    )
    db.add(ev)
    db.flush()
    db.add(EvidenceLink(atom_id=atom.id, evidence_id=ev.id, relation=str(relation)))
    events.record_event(
        db,
        events.EVIDENCE_ADDED,
        actor,
        atom.id,
        {"evidence_id": str(ev.id), "type": ev.type, "relation": str(relation)},
    )
    return ev


def add_evidence(
    db: Session, atom_id: str, *, actor: str, origin: Origin, **evidence_fields: Any
) -> Evidence:
    atom = get_atom(db, atom_id)
    ev = _add_evidence(db, atom, actor=actor, origin=origin, **evidence_fields)
    contradiz = (
        str(evidence_fields.get("relation", EvidenceRelation.SUPPORTS))
        == EvidenceRelation.CONTRADICTS
    )
    if not contradiz:
        return ev

    canonical = atom.status == LifecycleStatus.CANONICAL
    if canonical:
        # §74: evidência contraditória sobre canonical não altera a regra — desafia.
        events.record_event(
            db,
            events.CANONICAL_KNOWLEDGE_CHALLENGED,
            actor,
            atom.id,
            {"evidence_id": str(ev.id)},
        )
        # §73: "New conflicting evidence found" — owners do escopo são avisados
        from app.services import notify

        notify.notify_owners(
            db,
            atom,
            type="canonical_challenged",
            message=f"Nova evidência contraditória em canonical: {atom.title}",
        )
    # §48/§74: evidência incompatível abre Conflict (canonical: Reevaluation Request)
    if atom.kind != str(AtomKind.CONFLICT):
        from app.services import conflicts

        conflicts.ensure_conflict_for_atom(
            db, atom, actor=actor, evidence_id=str(ev.id), reevaluation=canonical
        )
    return ev


def update_atom(
    db: Session,
    atom_id: str,
    *,
    actor: str,
    expected_lock_version: int,
    changes: dict[str, Any],
) -> KnowledgeAtom:
    atom = get_atom(db, atom_id)
    _check_lock(atom, expected_lock_version)

    # §123: silent canonical overwrite é proibido — canonical muda por nova versão
    if atom.status in (str(LifecycleStatus.CANONICAL), str(LifecycleStatus.SUPERSEDED)):
        raise KernelError(
            f"Atom {atom.status} não pode ser editado diretamente; use new-version (§71-§72)"
        )

    invalid = set(changes) - MUTABLE_FIELDS
    if invalid:
        raise KernelError(f"Campos não editáveis: {sorted(invalid)}")

    diff: dict[str, list] = {}
    for field, new_value in changes.items():
        if field == "body":
            new_value = validate_body(atom.kind, new_value)
        if field == "classification" and new_value is not None:
            new_value = str(Classification(new_value))
        if field == "risk" and new_value is not None:
            new_value = str(RiskLevel(new_value))
        old = getattr(atom, field)
        if old != new_value:
            diff[field] = [old, new_value]
            setattr(atom, field, new_value)

    if diff:
        atom.lock_version += 1
        _snapshot(db, atom, actor)
        events.record_event(db, events.ATOM_UPDATED, actor, atom.id, {"changes": diff})
    return atom


def change_status(
    db: Session,
    atom_id: str,
    *,
    actor: str,
    new_status: LifecycleStatus,
    reason: str,
    expected_lock_version: int,
    authority_granted: bool = False,
    system_action: bool = False,
) -> KnowledgeAtom:
    """Transição de lifecycle com todos os gates.

    authority_granted deve ser True apenas após o chamador verificar RBAC de
    Decision Owner no escopo do atom (§8); system_action marca ações do
    Confidence/Policy Engine (Fase 2).
    """
    atom = get_atom(db, atom_id)
    _check_lock(atom, expected_lock_version)
    new_status = LifecycleStatus(new_status)
    lifecycle.validate_transition(LifecycleStatus(atom.status), new_status)
    if lifecycle.is_system_only(new_status) and not system_action:
        raise KernelError(f"Status {new_status} é definido apenas pelo sistema (§86)")
    if lifecycle.requires_authority(new_status) and not authority_granted:
        # Unauthorized canonical approval é integridade, não só permissão (§123)
        raise AuthorityError(f"Transição para {new_status} exige autoridade de Decision Owner")

    old_status = atom.status
    atom.status = str(new_status)
    atom.lock_version += 1
    _snapshot(db, atom, actor)
    events.record_event(
        db,
        events.STATUS_CHANGED,
        actor,
        atom.id,
        {"from": old_status, "to": str(new_status), "reason": reason},
    )
    if new_status == LifecycleStatus.NEEDS_HUMAN_REVIEW:
        events.record_event(db, events.HUMAN_REVIEW_REQUESTED, actor, atom.id, {"reason": reason})
    if new_status == LifecycleStatus.CANONICAL:
        events.record_event(
            db, events.KNOWLEDGE_CANONICALIZED, actor, atom.id, {"version": atom.version}
        )
    return atom


def new_canonical_version(
    db: Session,
    atom_id: str,
    *,
    actor: str,
    expected_lock_version: int,
    changes: dict[str, Any],
    reason: str,
) -> KnowledgeAtom:
    """§71-§72: RULE-A v1 → v2 no MESMO id; histórico preservado nos snapshots.

    O chamador deve ter verificado autoridade de Decision Owner (§8).
    """
    atom = get_atom(db, atom_id)
    _check_lock(atom, expected_lock_version)
    if atom.status != str(LifecycleStatus.CANONICAL):
        raise KernelError("new-version só se aplica a atoms CANONICAL")
    invalid = set(changes) - MUTABLE_FIELDS
    if invalid:
        raise KernelError(f"Campos não editáveis: {sorted(invalid)}")

    diff: dict[str, list] = {}
    for campo, novo in changes.items():
        if campo == "body":
            novo = validate_body(atom.kind, novo)
        old = getattr(atom, campo)
        if old != novo:
            diff[campo] = [old, novo]
            setattr(atom, campo, novo)
    if not diff:
        raise KernelError("Nova versão sem nenhuma alteração")

    atom.version += 1
    atom.lock_version += 1
    _snapshot(db, atom, actor)
    events.record_event(
        db,
        events.ATOM_UPDATED,
        actor,
        atom.id,
        {"changes": diff, "new_version": atom.version, "reason": reason},
    )
    events.record_event(
        db, events.KNOWLEDGE_CANONICALIZED, actor, atom.id, {"version": atom.version}
    )
    return atom


def supersede_with(
    db: Session,
    old_atom_id: str,
    *,
    new_atom_id: str,
    actor: str,
    expected_lock_version: int,
    reason: str,
) -> KnowledgeAtom:
    """§72: atom substituído por OUTRO atom — status SUPERSEDED + relação SUPERSEDES.

    O chamador deve ter verificado autoridade de Decision Owner (§8).
    """
    novo = get_atom(db, new_atom_id)
    if novo.status != str(LifecycleStatus.CANONICAL):
        raise KernelError("O atom substituto precisa estar CANONICAL")
    old = change_status(
        db,
        old_atom_id,
        actor=actor,
        new_status=LifecycleStatus.SUPERSEDED,
        reason=reason,
        expected_lock_version=expected_lock_version,
        authority_granted=True,
    )
    add_relation(
        db,
        actor=actor,
        from_atom=new_atom_id,
        to_atom=old_atom_id,
        relation_type=RelationType.SUPERSEDES,
    )
    return old


def add_relation(
    db: Session,
    *,
    actor: str,
    from_atom: str,
    to_atom: str,
    relation_type: RelationType,
) -> AtomRelation:
    get_atom(db, from_atom)
    get_atom(db, to_atom)
    if from_atom == to_atom:
        raise KernelError("Relação de um atom consigo mesmo não é permitida")
    relation_type = RelationType(relation_type)
    existing = db.scalar(
        select(AtomRelation).where(
            AtomRelation.from_atom == from_atom,
            AtomRelation.to_atom == to_atom,
            AtomRelation.type == str(relation_type),
        )
    )
    if existing:
        raise DuplicateError("Relação já existe")
    rel = AtomRelation(
        from_atom=from_atom, to_atom=to_atom, type=str(relation_type), created_by=actor
    )
    db.add(rel)
    events.record_event(
        db,
        events.RELATION_ADDED,
        actor,
        from_atom,
        {"to": to_atom, "type": str(relation_type)},
    )
    return rel


def atom_history(db: Session, atom_id: str) -> dict:
    """Audit trail (§69-§70): eventos + snapshots do atom."""
    get_atom(db, atom_id)
    evs = db.scalars(
        select(DomainEvent).where(DomainEvent.atom_id == atom_id).order_by(DomainEvent.id)
    ).all()
    versions = db.scalars(
        select(KnowledgeAtomVersion)
        .where(KnowledgeAtomVersion.atom_id == atom_id)
        .order_by(KnowledgeAtomVersion.rev)
    ).all()
    return {
        "events": [
            {
                "id": e.id,
                "type": e.event_type,
                "actor": e.actor,
                "payload": e.payload,
                "occurred_at": e.occurred_at.isoformat(),
            }
            for e in evs
        ],
        "versions": [
            {
                "rev": v.rev,
                "version": v.version,
                "created_by": v.created_by,
                "created_at": v.created_at.isoformat(),
                "snapshot": v.snapshot,
            }
            for v in versions
        ],
    }
