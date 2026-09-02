"""API do Discovery Engine: dispara runs (via fila `discovery`) e expõe auditoria/custo."""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.jobs import run_discovery_job
from app.kernel.errors import KernelError, NotFoundError
from app.models.auth import Role, User
from app.models.discovery import DiscoveryRun
from app.rbac.deps import require

router = APIRouter(prefix="/discovery", tags=["discovery"])


class RunIn(BaseModel):
    source_id: uuid.UUID
    agent: str = Field(pattern="^(code|test|corroboration)$")
    domain: str
    capability: str | None = None
    scope_hint: str = "todo o repositório"
    budget_usd: float = Field(default=5.0, gt=0, le=50)


def _out(r: DiscoveryRun) -> dict:
    return {
        "id": str(r.id),
        "source_id": str(r.source_id),
        "agent": r.agent,
        "status": r.status,
        "domain": r.domain,
        "capability": r.capability,
        "commit": r.commit,
        "model": r.model,
        "effort": r.effort,
        "cli_version": r.cli_version,
        "prompt_hash": r.prompt_hash,
        "session_id": r.session_id,
        "log_path": r.log_path,
        "cost_usd": r.cost_usd,
        "num_turns": r.num_turns,
        "candidates_created": r.candidates_created,
        "candidates_rejected": r.candidates_rejected,
        "questions_created": r.questions_created,
        "evidence_rejected": r.evidence_rejected,
        "duplicates_skipped": r.duplicates_skipped,
        "potential_duplicates": r.potential_duplicates,
        "workspace_clean": r.workspace_clean,
        "error": r.error,
        "created_by": r.created_by,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def create_run(
    body: RunIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    """Enfileira o run na fila `discovery` — consumida por um worker NO HOST
    (`uv run procrastinate --app=app.jobs.job_app worker --queues discovery`),
    pois o harness `claude` não existe no container."""
    try:
        run_discovery_job.defer(
            source_id=str(body.source_id),
            agent=body.agent,
            domain=body.domain,
            capability=body.capability,
            actor=admin.email,
            scope_hint=body.scope_hint,
            budget_usd=body.budget_usd,
        )
    except Exception as e:  # fila indisponível não pode virar 500 silencioso
        raise KernelError(f"Falha ao enfileirar discovery: {e}") from None
    return {"queued": True, "queue": "discovery"}


@router.get("/runs")
def list_runs(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    domain: str | None = None,
) -> list[dict]:
    stmt = select(DiscoveryRun).order_by(DiscoveryRun.started_at.desc()).limit(100)
    if domain:
        stmt = stmt.where(DiscoveryRun.domain == domain)
    return [_out(r) for r in db.scalars(stmt)]


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    r = db.get(DiscoveryRun, run_id)
    if r is None:
        raise NotFoundError("Run não encontrado")
    return _out(r)
