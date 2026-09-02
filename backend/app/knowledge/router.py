"""API /knowledge (PRD §94). Escrita sempre via services (kernel gates)."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth.deps import get_current_user
from app.db import get_db
from app.jobs import defer_export
from app.kernel import lifecycle
from app.kernel.errors import NotFoundError
from app.kernel.ir.envelope import (
    AtomKind,
    Classification,
    EvidenceRelation,
    EvidenceType,
    LifecycleStatus,
    Origin,
    RelationType,
    RiskLevel,
)
from app.kernel.linter import lint_db
from app.models.auth import Role, User
from app.models.knowledge import KnowledgeAtom
from app.rbac.deps import ensure_scope_role
from app.services import evaluation
from app.services import knowledge as svc

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# ---------- Schemas ----------


class EvidenceIn(BaseModel):
    type: EvidenceType
    source_id: uuid.UUID | None = None
    location: dict | None = None
    summary: str | None = None
    excerpt: str | None = None
    metadata: dict | None = None
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS


class CandidateIn(BaseModel):
    kind: AtomKind
    title: str = Field(min_length=1, max_length=300)
    domain: str
    capability: str | None = None
    description: str | None = None
    classification: Classification | None = None
    risk: RiskLevel | None = None
    scope: dict | None = None
    effective: dict | None = None
    body: dict | None = None
    id: str | None = None
    evidence: list[EvidenceIn] = Field(default_factory=list)


class AtomPatch(BaseModel):
    expected_lock_version: int
    title: str | None = None
    description: str | None = None
    classification: Classification | None = None
    risk: RiskLevel | None = None
    scope: dict | None = None
    effective: dict | None = None
    body: dict | None = None


class StatusIn(BaseModel):
    status: LifecycleStatus
    reason: str = Field(min_length=1)
    expected_lock_version: int


class RelationIn(BaseModel):
    to_atom: str
    type: RelationType


class NewVersionIn(BaseModel):
    expected_lock_version: int
    reason: str = Field(min_length=1)
    title: str | None = None
    description: str | None = None
    classification: Classification | None = None
    risk: RiskLevel | None = None
    scope: dict | None = None
    effective: dict | None = None
    body: dict | None = None


class SupersedeIn(BaseModel):
    by: str  # id do atom canonical substituto
    reason: str = Field(min_length=1)
    expected_lock_version: int


def _atom_out(atom: KnowledgeAtom) -> dict:
    return {
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
        "lock_version": atom.lock_version,
        "created_by": atom.created_by,
        "created_at": atom.created_at.isoformat(),
        "updated_at": atom.updated_at.isoformat(),
    }


# ---------- Endpoints ----------


@router.get("")
def list_atoms(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    kind: AtomKind | None = None,
    domain: str | None = None,
    capability: str | None = None,
    status_: LifecycleStatus | None = Query(default=None, alias="status"),
    classification: Classification | None = None,
    risk: RiskLevel | None = None,
    origin: Origin | None = None,
    q: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    max_confidence: float | None = Query(default=None, ge=0, le=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    stmt = select(KnowledgeAtom)
    if kind:
        stmt = stmt.where(KnowledgeAtom.kind == str(kind))
    if domain:
        stmt = stmt.where(KnowledgeAtom.domain == domain)
    if capability:
        stmt = stmt.where(KnowledgeAtom.capability == capability)
    if status_:
        stmt = stmt.where(KnowledgeAtom.status == str(status_))
    if classification:
        stmt = stmt.where(KnowledgeAtom.classification == str(classification))
    if risk:
        stmt = stmt.where(KnowledgeAtom.risk == str(risk))
    if origin:
        stmt = stmt.where(KnowledgeAtom.origin == str(origin))
    if q:
        stmt = stmt.where(KnowledgeAtom.title.ilike(f"%{q}%"))
    if min_confidence is not None:
        stmt = stmt.where(KnowledgeAtom.confidence >= min_confidence)
    if max_confidence is not None:
        stmt = stmt.where(KnowledgeAtom.confidence <= max_confidence)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    atoms = db.scalars(
        stmt.order_by(KnowledgeAtom.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return {"total": total, "items": [_atom_out(a) for a in atoms]}


@router.post("/candidates", status_code=status.HTTP_201_CREATED)
def create_candidate(
    body: CandidateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ensure_scope_role(user, Role.REVIEWER, body.domain, body.capability)
    atom = svc.create_candidate(
        db,
        actor=user.email,
        origin=Origin.HUMAN,
        kind=body.kind,
        title=body.title,
        domain=body.domain,
        capability=body.capability,
        description=body.description,
        classification=body.classification,
        risk=body.risk,
        scope=body.scope,
        effective=body.effective,
        body=body.body,
        atom_id=body.id,
        evidence=[e.model_dump() for e in body.evidence],
    )
    db.commit()
    return _atom_out(atom)


@router.get("/lint")
def run_linter(
    db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> dict:
    findings = lint_db(db)
    return {
        "errors": sum(1 for f in findings if f.severity == "error"),
        "warnings": sum(1 for f in findings if f.severity == "warning"),
        "findings": [f.as_dict() for f in findings],
    }


@router.get("/{atom_id}")
def get_atom(
    atom_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> dict:
    return _atom_out(svc.get_atom(db, atom_id))


@router.patch("/{atom_id}")
def patch_atom(
    atom_id: str,
    body: AtomPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = svc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    changes = body.model_dump(exclude={"expected_lock_version"}, exclude_none=True)
    atom = svc.update_atom(
        db,
        atom_id,
        actor=user.email,
        expected_lock_version=body.expected_lock_version,
        changes=changes,
    )
    db.commit()
    return _atom_out(atom)


@router.post("/{atom_id}/status")
def change_status(
    atom_id: str,
    body: StatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = svc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    authority = False
    if lifecycle.requires_authority(body.status):
        # Canonicalizar/superseder exige Decision Owner no escopo (§8, AC-GOV-03)
        ensure_scope_role(user, Role.DECISION_OWNER, atom.domain, atom.capability)
        authority = True
    atom = svc.change_status(
        db,
        atom_id,
        actor=user.email,
        new_status=body.status,
        reason=body.reason,
        expected_lock_version=body.expected_lock_version,
        authority_granted=authority,
    )
    db.commit()
    if authority:  # entrou/saiu do canonical space → sincroniza o repo git
        defer_export(trigger=f"status:{atom.id}")
    return _atom_out(atom)


@router.post("/{atom_id}/evidence", status_code=status.HTTP_201_CREATED)
def add_evidence(
    atom_id: str,
    body: EvidenceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = svc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    ev = svc.add_evidence(
        db, atom_id, actor=user.email, origin=Origin.HUMAN, **body.model_dump()
    )
    db.commit()
    return {"id": str(ev.id), "type": ev.type, "relation": str(body.relation)}


@router.get("/{atom_id}/evidence")
def list_evidence(
    atom_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> list[dict]:
    atom = db.get(
        KnowledgeAtom,
        atom_id,
        options=[selectinload(KnowledgeAtom.evidence_links)],
    )
    if atom is None:
        raise NotFoundError(f"Atom não encontrado: {atom_id}")
    out = []
    for link in atom.evidence_links:
        ev = link.evidence
        out.append(
            {
                "id": str(ev.id),
                "type": ev.type,
                "relation": link.relation,
                "summary": ev.summary,
                "excerpt": ev.excerpt,
                "location": ev.location,
                "source_id": str(ev.source_id) if ev.source_id else None,
                "origin": ev.origin,
                "created_by": ev.created_by,
                "created_at": ev.created_at.isoformat(),
            }
        )
    return out


@router.post("/{atom_id}/relations", status_code=status.HTTP_201_CREATED)
def add_relation(
    atom_id: str,
    body: RelationIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = svc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    rel = svc.add_relation(
        db, actor=user.email, from_atom=atom_id, to_atom=body.to_atom, relation_type=body.type
    )
    db.commit()
    return {"id": str(rel.id), "from": rel.from_atom, "to": rel.to_atom, "type": rel.type}


@router.post("/{atom_id}/evidence/{evidence_id}/translate")
def translate_evidence_endpoint(
    atom_id: str,
    evidence_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Tradução de negócio para evidence sem summary (§46), via porta LLMProvider."""
    from app.llm.provider import translate_evidence
    from app.models.knowledge import Evidence

    atom = svc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise NotFoundError("Evidence não encontrada")
    if not ev.excerpt:
        raise NotFoundError("Evidence sem trecho técnico para traduzir")
    if ev.summary:
        return {"id": str(ev.id), "summary": ev.summary, "translated": False}
    contexto = f"{atom.title} ({atom.domain}/{atom.capability or '-'})"
    ev.summary = translate_evidence(ev.excerpt, contexto)
    db.commit()
    return {"id": str(ev.id), "summary": ev.summary, "translated": True}


@router.get("/{atom_id}/history")
def history(
    atom_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> dict:
    return svc.atom_history(db, atom_id)


@router.post("/{atom_id}/evaluate")
def evaluate(
    atom_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = svc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    summary = evaluation.evaluate_atom(db, atom_id, trigger=f"manual:{user.email}")
    db.commit()
    if summary.get("decision") == "AUTO_APPROVED":
        defer_export(trigger=f"auto-approval:{atom_id}")
    return summary


@router.get("/{atom_id}/confidence")
def confidence(
    atom_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> dict:
    latest = evaluation.latest_confidence(db, atom_id)
    if latest is None:
        raise NotFoundError(f"Atom {atom_id} ainda não foi avaliado")
    return latest


@router.post("/{atom_id}/new-version")
def new_version(
    atom_id: str,
    body: NewVersionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = svc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.DECISION_OWNER, atom.domain, atom.capability)
    changes = body.model_dump(
        exclude={"expected_lock_version", "reason"}, exclude_none=True
    )
    atom = svc.new_canonical_version(
        db,
        atom_id,
        actor=user.email,
        expected_lock_version=body.expected_lock_version,
        changes=changes,
        reason=body.reason,
    )
    db.commit()
    defer_export(trigger=f"new-version:{atom_id}")
    return _atom_out(atom)


@router.post("/{atom_id}/supersede")
def supersede(
    atom_id: str,
    body: SupersedeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = svc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.DECISION_OWNER, atom.domain, atom.capability)
    atom = svc.supersede_with(
        db,
        atom_id,
        new_atom_id=body.by,
        actor=user.email,
        expected_lock_version=body.expected_lock_version,
        reason=body.reason,
    )
    db.commit()
    defer_export(trigger=f"supersede:{atom_id}")
    return _atom_out(atom)
