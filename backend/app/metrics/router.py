"""API de Semantic Metrics (PRD §75-§81, §107-§109)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.models.auth import User
from app.models.knowledge import DomainEvent
from app.services import metrics as msvc

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/coverage")
def coverage(
    domain: str | None = None,
    capability: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return msvc.coverage(db, domain=domain, capability=capability)


@router.get("/coverage-by-capability")
def coverage_by_capability(
    domain: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[dict]:
    return msvc.coverage_by_capability(db, domain=domain)


@router.get("/confidence-distribution")
def confidence_distribution(
    domain: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return msvc.confidence_distribution(db, domain=domain)


@router.get("/attention")
def attention(
    domain: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return msvc.attention_kpis(db, domain=domain)


@router.get("/audit")
def audit(
    domain: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return msvc.audit_dashboard(db, domain=domain)


@router.get("/recent-events")
def recent_events(
    limit: int = 20,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[dict]:
    """§107: Recent Knowledge Changes."""
    rows = db.scalars(
        select(DomainEvent).order_by(DomainEvent.id.desc()).limit(min(limit, 100))
    ).all()
    return [
        {
            "type": e.event_type,
            "atom_id": e.atom_id,
            "actor": e.actor,
            "at": e.occurred_at.isoformat(),
        }
        for e in rows
    ]
