"""Source Registry (PRD §10)."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.kernel.errors import NotFoundError
from app.kernel.ir.envelope import SourceType
from app.models.auth import Role, User
from app.models.knowledge import Source
from app.rbac.deps import require
from app.services import inventory as invsvc

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceIn(BaseModel):
    type: SourceType
    name: str = Field(min_length=1, max_length=200)
    location: str | None = None
    repository: str | None = None
    branch: str | None = None
    commit: str | None = None
    version: str | None = None
    domain_slug: str | None = None
    metadata: dict | None = None


def _out(s: Source) -> dict:
    return {
        "id": str(s.id),
        "type": s.type,
        "name": s.name,
        "location": s.location,
        "repository": s.repository,
        "branch": s.branch,
        "commit": s.commit,
        "version": s.version,
        "domain_slug": s.domain_slug,
        "metadata": s.meta,
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat(),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_source(
    body: SourceIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    src = Source(
        type=str(body.type),
        name=body.name,
        location=body.location,
        repository=body.repository,
        branch=body.branch,
        commit=body.commit,
        version=body.version,
        domain_slug=body.domain_slug,
        meta=body.metadata,
        created_by=admin.email,
    )
    db.add(src)
    db.commit()
    return _out(src)


@router.get("")
def list_sources(
    db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> list[dict]:
    return [_out(s) for s in db.scalars(select(Source).order_by(Source.created_at))]


@router.get("/{source_id}")
def get_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    src = db.get(Source, source_id)
    if src is None:
        raise NotFoundError(f"Source não encontrada: {source_id}")
    return _out(src)


@router.get("/{source_id}/inventory/summary")
def inventory_summary(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    """Quantos arquivos foram inventariados, por capability, e capabilities sugeridas."""
    if db.get(Source, source_id) is None:
        raise NotFoundError(f"Source não encontrada: {source_id}")
    return invsvc.inventory_summary(db, source_id)


@router.get("/{source_id}/inventory")
def inventory_files(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    capability: str | None = None,
    q: str | None = Query(default=None, description="filtro em caminho/resumo"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[dict]:
    if db.get(Source, source_id) is None:
        raise NotFoundError(f"Source não encontrada: {source_id}")
    return invsvc.list_inventory(db, source_id, capability=capability, q=q, limit=limit)
