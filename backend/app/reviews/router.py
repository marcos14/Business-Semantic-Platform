"""API do Semantic Governance Workspace (PRD §95)."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.jobs import defer_export
from app.kernel.governance import DecisionAction, ReviewAction
from app.kernel.ir.envelope import Classification
from app.models.auth import Role, User
from app.rbac.deps import ensure_scope_role
from app.services import knowledge as ksvc
from app.services import review as rsvc

router = APIRouter(prefix="/reviews", tags=["reviews"])


class VoteIn(BaseModel):
    action: ReviewAction
    comment: str | None = None


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class RequestEvidenceIn(BaseModel):
    note: str = Field(min_length=1)


class ExceptionIn(BaseModel):
    title: str = Field(min_length=1)
    condition: str = Field(min_length=1)


class DecisionIn(BaseModel):
    action: DecisionAction
    reason: str = Field(min_length=1)
    expected_lock_version: int
    classification: Classification | None = None
    exception: ExceptionIn | None = None


@router.get("/inbox")
def inbox(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return rsvc.inbox(db, user)


@router.get("/kanban")
def kanban(
    domain: str | None = None,
    capability: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return rsvc.kanban(db, user, domain, capability)


@router.get("/{atom_id}")
def decision_room(
    atom_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    return rsvc.decision_room(db, atom_id, user)


@router.post("/{atom_id}/start")
def start_review(
    atom_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    atom = ksvc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    atom = rsvc.start_review(db, atom_id, user)
    db.commit()
    return {"id": atom.id, "status": atom.status, "lock_version": atom.lock_version}


@router.post("/{atom_id}/vote", status_code=status.HTTP_201_CREATED)
def vote(
    atom_id: str,
    body: VoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = ksvc.get_atom(db, atom_id)
    # AC-GOV-01: reviewer (no escopo) pode votar
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    v = rsvc.submit_vote(db, atom_id, user, body.action, body.comment)
    db.commit()
    return {"action": v.action, "role": v.role_at_vote, "domain_expert": v.is_domain_expert}


@router.post("/{atom_id}/comment", status_code=status.HTTP_201_CREATED)
def comment(
    atom_id: str,
    body: CommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = ksvc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    c = rsvc.add_comment(db, atom_id, user, body.text)
    db.commit()
    return {"id": str(c.id), "at": c.created_at.isoformat()}


@router.post("/{atom_id}/request-evidence")
def request_evidence(
    atom_id: str,
    body: RequestEvidenceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = ksvc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    atom = rsvc.request_evidence(db, atom_id, user, body.note)
    db.commit()
    return {"id": atom.id, "status": atom.status, "lock_version": atom.lock_version}


@router.post("/{atom_id}/ready-for-decision")
def ready_for_decision(
    atom_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    atom = ksvc.get_atom(db, atom_id)
    ensure_scope_role(user, Role.REVIEWER, atom.domain, atom.capability)
    atom = rsvc.ready_for_decision(db, atom_id, user)
    db.commit()
    return {"id": atom.id, "status": atom.status, "lock_version": atom.lock_version}


@router.post("/{atom_id}/decision")
def decision(
    atom_id: str,
    body: DecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    atom = ksvc.get_atom(db, atom_id)
    # AC-GOV-02/03: só Decision Owner (ou admin) no escopo decide
    ensure_scope_role(user, Role.DECISION_OWNER, atom.domain, atom.capability)
    atom = rsvc.decide(
        db,
        atom_id,
        user,
        action=body.action,
        reason=body.reason,
        expected_lock_version=body.expected_lock_version,
        classification=body.classification,
        exception=body.exception.model_dump() if body.exception else None,
    )
    db.commit()
    if atom.status in ("CANONICAL", "SUPERSEDED"):
        defer_export(trigger=f"decision:{atom_id}")
    return {"id": atom.id, "status": atom.status, "lock_version": atom.lock_version}
