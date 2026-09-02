"""API /conflicts (PRD §96): listagem, Conflict View (§49), detecção e resolução (§50)."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.deps import get_current_user
from app.db import get_db
from app.kernel.errors import KernelError, NotFoundError
from app.kernel.ir.envelope import AtomKind
from app.models.auth import Role, User
from app.models.knowledge import KnowledgeAtom
from app.models.review import Vote
from app.rbac.deps import ensure_scope_role
from app.services import conflicts as csvc
from app.services import knowledge as ksvc
from app.services.evaluation import latest_confidence

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


class DetectIn(BaseModel):
    domain: str
    capability: str | None = None
    use_llm: bool = False


class ResolveIn(BaseModel):
    action: csvc.ConflictResolution
    reason: str = Field(min_length=1)
    expected_lock_version: int
    params: dict = Field(default_factory=dict)


def _conflict_out(c: KnowledgeAtom) -> dict:
    body = c.body or {}
    return {
        "id": c.id,
        "title": c.title,
        "domain": c.domain,
        "capability": c.capability,
        "status": c.status,
        "topic": body.get("topic"),
        "about": body.get("about"),
        "assertions": body.get("assertions", []),
        "reevaluation": body.get("reevaluation", False),
        "state": body.get("state"),
        "resolution": body.get("resolution"),
        "lock_version": c.lock_version,
        "created_by": c.created_by,
        "created_at": c.created_at.isoformat(),
    }


@router.get("")
def list_conflicts(
    domain: str | None = None,
    state: str | None = "open",
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = select(KnowledgeAtom).where(KnowledgeAtom.kind == str(AtomKind.CONFLICT))
    if domain:
        stmt = stmt.where(KnowledgeAtom.domain == domain)
    if state:
        stmt = stmt.where(KnowledgeAtom.body["state"].astext == state)
    rows = db.scalars(stmt.order_by(KnowledgeAtom.created_at.desc())).all()
    return [_conflict_out(c) for c in rows]


@router.post("/detect")
def detect(
    body: DetectIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ensure_scope_role(user, Role.REVIEWER, body.domain, body.capability)
    criados = csvc.detect_conflicts(
        db, domain=body.domain, capability=body.capability, actor=f"detect:{user.email}"
    )
    if body.use_llm:
        criados += csvc.detect_conflicts_llm(
            db, domain=body.domain, capability=body.capability, actor=f"detect-llm:{user.email}"
        )
    db.commit()
    return {"created": criados}


@router.get("/{conflict_id}")
def conflict_view(
    conflict_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    """Conflict View (§49): assertions em disputa, evidence e confidence de cada lado."""
    c = ksvc.get_atom(db, conflict_id)
    if c.kind != str(AtomKind.CONFLICT):
        raise KernelError(f"{conflict_id} não é um conflict")
    out = _conflict_out(c)

    lados = []
    for atom_id in [out["about"]] if out["about"] else [a["atom_id"] for a in out["assertions"]]:
        if not atom_id:
            continue
        try:
            atom = db.get(
                KnowledgeAtom, atom_id, options=[selectinload(KnowledgeAtom.evidence_links)]
            )
            if atom is None:
                raise NotFoundError(atom_id)
        except NotFoundError:
            continue
        lados.append(
            {
                "atom": {
                    "id": atom.id,
                    "title": atom.title,
                    "statement": (atom.body or {}).get("statement"),
                    "status": atom.status,
                    "classification": atom.classification,
                    "confidence": atom.confidence,
                    "risk": atom.risk,
                    "scope": atom.scope,
                },
                "confidence": latest_confidence(db, atom.id),
                "evidence": [
                    {
                        "id": str(link.evidence.id),
                        "type": link.evidence.type,
                        "relation": link.relation,
                        "summary": link.evidence.summary,
                        "location": link.evidence.location,
                        "excerpt": link.evidence.excerpt,
                        "created_by": link.evidence.created_by,
                    }
                    for link in atom.evidence_links
                ],
            }
        )
    votos = db.scalars(
        select(Vote).where(Vote.atom_id == conflict_id).options(selectinload(Vote.reviewer))
    ).all()
    out["sides"] = lados
    out["votes"] = [
        {"reviewer": v.reviewer.name, "action": v.action, "comment": v.comment}
        for v in votos
    ]
    return out


@router.post("/{conflict_id}/resolve", status_code=status.HTTP_200_OK)
def resolve(
    conflict_id: str,
    body: ResolveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    c = ksvc.get_atom(db, conflict_id)
    # AC-CON-03: resolução é do Decision Owner no escopo
    ensure_scope_role(user, Role.DECISION_OWNER, c.domain, c.capability)
    c = csvc.resolve_conflict(
        db,
        conflict_id,
        user,
        action=body.action,
        reason=body.reason,
        expected_lock_version=body.expected_lock_version,
        params=body.params,
    )
    db.commit()
    return _conflict_out(c)
