"""API do Discovery Engine: dispara runs (via fila `discovery`) e expõe auditoria/custo."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.jobs import (
    plan_inventory_job,
    release_scheduled,
    run_directed_job,
    run_discovery_job,
)
from app.kernel.errors import InvalidTransitionError, KernelError, NotFoundError
from app.models.auth import Role, User
from app.models.discovery import DiscoveryRun
from app.models.knowledge import Source
from app.rbac.deps import require
from app.services import discovery as dsvc
from app.services import inventory as invsvc

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
        "batch_id": str(r.batch_id) if r.batch_id else None,
        "target_file": r.target_file,
        "line_range": r.line_range,
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
        "reinforcements": r.reinforcements,
        "systemic_created": r.systemic_created,
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
    exclude: str | None = Query(
        default=None, description="status a omitir, separados por vírgula (ex.: limit)"
    ),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    stmt = select(DiscoveryRun).order_by(DiscoveryRun.started_at.desc()).limit(limit)
    if domain:
        stmt = stmt.where(DiscoveryRun.domain == domain)
    if exclude:
        omitir = [s.strip() for s in exclude.split(",") if s.strip()]
        if omitir:
            stmt = stmt.where(DiscoveryRun.status.not_in(omitir))
    return [_out(r) for r in db.scalars(stmt)]


# ---------- Triagem de relevância dos pendentes ----------


class TriageIn(BaseModel):
    domain: str | None = None
    limit: int = Field(default=200, ge=1, le=1000)
    apply: bool = Field(default=True, description="false = só classifica e conta, sem mexer")


@router.post("/triage")
def triage_pending_endpoint(
    body: TriageIn | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    """Aplica a régua de relevância aos candidates que esperam revisão humana sem voto:
    classifica via modelo de análise (OPENROUTER_MODEL) e re-roteia SYSTEMIC/LOW."""
    from app.services.triage import triage_pending

    body = body or TriageIn()
    try:
        return triage_pending(db, domain=body.domain, limit=body.limit, apply=body.apply)
    except RuntimeError as e:  # provider sem chave etc.
        raise KernelError(f"Triagem indisponível: {e}") from None


# ---------- Inventário e campanhas (muitos runs pequenos) ----------


class InventoryIn(BaseModel):
    source_id: uuid.UUID
    domain: str
    prefix: str | None = Field(
        default=None, description="só arquivos sob este prefixo (ex.: ADM001/)"
    )
    max_files: int | None = Field(default=None, ge=1, le=20000)
    only_missing: bool = True
    budget_usd: float = Field(default=3.0, gt=0, le=50, description="por lote")


class CampaignIn(BaseModel):
    source_id: uuid.UUID
    domain: str
    capability: str
    min_relevance: int = Field(default=2, ge=1, le=3)
    max_files: int | None = Field(default=None, ge=1, le=5000)
    budget_usd: float = Field(default=3.0, gt=0, le=50, description="por arquivo/faixa (um turno)")
    max_candidates: int = Field(default=12, ge=1, le=100)


def _source_ou_404(db: Session, source_id: uuid.UUID) -> Source:
    src = db.get(Source, source_id)
    if src is None:
        raise NotFoundError(f"Source não encontrada: {source_id}")
    if not src.repository:
        raise KernelError("Source sem repositório: inventário/discovery exigem código-fonte")
    return src


@router.post("/inventory", status_code=status.HTTP_202_ACCEPTED)
def start_inventory(
    body: InventoryIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    """Enfileira o PLANEJAMENTO do inventário. O worker no host (que vê o repositório)
    enumera os fontes, monta os lotes e enfileira um job por lote na mesma campanha."""
    src = _source_ou_404(db, body.source_id)
    if not invsvc.capabilities_of(db, body.domain):
        raise KernelError(
            f"Domain '{body.domain}' sem capabilities cadastradas: o inventário liga arquivos "
            "a capabilities. Cadastre-as em Admin antes."
        )
    batch_id = uuid.uuid4()
    try:
        plan_inventory_job.defer(
            source_id=str(src.id), domain=body.domain, prefix=body.prefix,
            max_files=body.max_files, only_missing=body.only_missing, actor=admin.email,
            batch_id=str(batch_id), budget_usd=body.budget_usd,
        )
    except Exception as e:
        raise KernelError(f"Falha ao enfileirar inventário: {e}") from None
    return {"batch_id": str(batch_id), "planning": True, "queue": "discovery"}


@router.post("/campaigns", status_code=status.HTTP_202_ACCEPTED)
def start_campaign(
    body: CampaignIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    """Discovery dirigido: um job por arquivo (ou faixa de linhas) ligado à capability."""
    src = _source_ou_404(db, body.source_id)
    plano = dsvc.plan_directed(
        db, src, capability=body.capability, min_relevance=body.min_relevance,
        max_files=body.max_files,
    )
    if not plano:
        raise KernelError(
            f"Nenhum arquivo inventariado para a capability '{body.capability}' com relevância "
            f">= {body.min_relevance}. Rode o inventário desta source primeiro."
        )
    batch_id = uuid.uuid4()
    try:
        for t in plano:
            run_directed_job.defer(
                source_id=str(src.id), domain=body.domain, capability=body.capability,
                file=t["file"], start_line=t["start_line"], end_line=t["end_line"],
                actor=admin.email, batch_id=str(batch_id), budget_usd=body.budget_usd,
                max_candidates=body.max_candidates,
            )
    except Exception as e:
        raise KernelError(f"Falha ao enfileirar campanha: {e}") from None
    arquivos = len({t["file"] for t in plano})
    return {"batch_id": str(batch_id), "files": arquivos, "jobs": len(plano), "queue": "discovery"}


_BATCH_JOBS_SQL = text(
    """
    select args->>'batch_id' as batch_id, task_name, status::text as status, count(*) as n,
           min(args->>'source_id') as source_id, min(args->>'domain') as domain,
           min(args->>'capability') as capability
    from procrastinate_jobs
    where queue_name = 'discovery' and args ? 'batch_id'
    group by 1, 2, 3
    """
)


@router.get("/batches")
def list_batches(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """Campanhas (inventário / dirigido): progresso agregado de runs + jobs ainda na fila."""
    r = DiscoveryRun
    rows = db.execute(
        select(
            r.batch_id, r.agent, r.domain, r.capability, r.source_id,
            func.count().label("runs"),
            func.sum(case((r.status == "succeeded", 1), else_=0)).label("succeeded"),
            func.sum(case((r.status == "failed", 1), else_=0)).label("failed"),
            func.sum(case((r.status == "running", 1), else_=0)).label("running"),
            func.sum(case((r.status.in_(["limit", "auth_failed"]), 1), else_=0)).label("blocked"),
            func.sum(r.cost_usd).label("cost_usd"),
            func.sum(r.candidates_created).label("candidates"),
            func.sum(r.questions_created).label("questions"),
            func.sum(r.evidence_rejected).label("evidence_rejected"),
            func.min(r.started_at).label("started_at"),
            func.max(r.finished_at).label("finished_at"),
        )
        .where(r.batch_id.is_not(None))
        .group_by(r.batch_id, r.agent, r.domain, r.capability, r.source_id)
        .order_by(func.min(r.started_at).desc())
        .limit(limit)
    ).all()
    batches: dict[str, dict] = {}
    for row in rows:
        bid = str(row.batch_id)
        batches[bid] = {
            "batch_id": bid,
            "agent": row.agent,
            "domain": row.domain,
            "capability": row.capability,
            "source_id": str(row.source_id),
            "runs": row.runs,
            "succeeded": int(row.succeeded or 0),
            "failed": int(row.failed or 0),
            "running": int(row.running or 0),
            "blocked": int(row.blocked or 0),
            "cost_usd": float(row.cost_usd or 0),
            "candidates": int(row.candidates or 0),
            "questions": int(row.questions or 0),
            "evidence_rejected": int(row.evidence_rejected or 0),
            "pending_jobs": 0,
            "doing_jobs": 0,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
    try:
        jobs = db.execute(_BATCH_JOBS_SQL).all()
    except ProgrammingError:
        db.rollback()
        jobs = []
    for j in jobs:
        if not j.batch_id:
            continue
        b = batches.setdefault(
            j.batch_id,
            {
                "batch_id": j.batch_id,
                "agent": "inventory" if j.task_name in ("jobs.run_inventory", "jobs.plan_inventory")
                else "code",
                "domain": j.domain, "capability": j.capability, "source_id": j.source_id,
                "runs": 0, "succeeded": 0, "failed": 0, "running": 0, "blocked": 0,
                "cost_usd": 0.0, "candidates": 0, "questions": 0, "evidence_rejected": 0,
                "pending_jobs": 0, "doing_jobs": 0, "started_at": None, "finished_at": None,
            },
        )
        if j.status == "todo":
            b["pending_jobs"] += j.n
        elif j.status == "doing":
            b["doing_jobs"] += j.n
    saida = list(batches.values())
    for b in saida:
        # Um run 'limit'/'auth_failed' NÃO conclui o item: o job volta para a fila e
        # reaparece em pending_jobs. Progresso conta só o que terminou de verdade.
        em_andamento = max(b["running"], b["doing_jobs"])
        b["done"] = b["succeeded"] + b["failed"]
        b["total"] = b["done"] + b["pending_jobs"] + em_andamento
        b["active"] = b["pending_jobs"] > 0 or em_andamento > 0
    saida.sort(key=lambda b: (not b["active"], b["started_at"] or ""), reverse=False)
    return saida


# ---------- Fila (Procrastinate) ----------

WORKER_ALIVE_SECONDS = 60  # heartbeat mais antigo que isso = worker considerado morto

_QUEUE_JOBS_SQL = text(
    """
    select j.id, j.queue_name, j.task_name, j.status::text as status, j.attempts,
           j.scheduled_at, j.abort_requested, j.worker_id, j.args,
           (select min(e.at) from procrastinate_events e where e.job_id = j.id) as created_at,
           (select max(e.at) from procrastinate_events e where e.job_id = j.id) as updated_at
    from procrastinate_jobs j
    where cast(:queue as varchar) is null or j.queue_name = :queue
    order by j.id desc
    limit :limit
    """
)
_QUEUE_SUMMARY_SQL = text(
    """
    select status::text as status, count(*) as n
    from procrastinate_jobs
    where cast(:queue as varchar) is null or queue_name = :queue
    group by status
    """
)
_WORKERS_SQL = text("select id, last_heartbeat from procrastinate_workers order by id")
_FUTURE_SQL = text(
    """
    select count(*) as n, min(scheduled_at) as proximo
    from procrastinate_jobs
    where status = 'todo' and scheduled_at > now()
      and (cast(:queue as varchar) is null or queue_name = :queue)
    """
)
_CANCEL_SQL = text(
    "update procrastinate_jobs set status = 'cancelled' "
    "where id = :id and status = 'todo' returning id"
)


def _job_out(row) -> dict:
    return {
        "id": row.id,
        "queue": row.queue_name,
        "task": row.task_name,
        "status": row.status,
        "attempts": row.attempts,
        "abort_requested": row.abort_requested,
        "worker_id": row.worker_id,
        "args": row.args,
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/queue")
def list_queue(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    queue: str | None = Query(default="discovery", description="null = todas as filas"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Estado da fila do Procrastinate (tabela `procrastinate_jobs`) e heartbeat dos workers.

    Os jobs da fila `discovery` só andam com um worker NO HOST; a tela usa `pending`
    + `workers_alive` para avisar quando há job parado sem ninguém consumindo.
    """
    params = {"queue": queue or None, "limit": limit}
    try:
        jobs = db.execute(_QUEUE_JOBS_SQL, params).all()
        summary = db.execute(_QUEUE_SUMMARY_SQL, {"queue": params["queue"]}).all()
        workers = db.execute(_WORKERS_SQL).all()
        futuro = db.execute(_FUTURE_SQL, {"queue": params["queue"]}).first()
    except ProgrammingError:
        # schema do procrastinate ainda não aplicado (worker nunca subiu)
        db.rollback()
        return {
            "schema_missing": True, "queue": queue, "jobs": [], "by_status": {},
            "pending": 0, "running": 0, "workers": [], "workers_alive": 0,
            "scheduled_future": 0, "next_scheduled_at": None,
        }
    now = datetime.now(UTC)
    limite = now - timedelta(seconds=WORKER_ALIVE_SECONDS)
    by_status = {r.status: r.n for r in summary}
    workers_out = [
        {
            "id": w.id,
            "last_heartbeat": w.last_heartbeat.isoformat(),
            "alive": w.last_heartbeat >= limite,
        }
        for w in workers
    ]
    return {
        "schema_missing": False,
        "queue": queue,
        "jobs": [_job_out(j) for j in jobs],
        "by_status": by_status,
        "pending": by_status.get("todo", 0),
        "running": by_status.get("doing", 0),
        "workers": workers_out,
        "workers_alive": sum(1 for w in workers_out if w["alive"]),
        # jobs reagendados para depois (tipicamente esperando o reset da franquia)
        "scheduled_future": int(futuro.n or 0) if futuro else 0,
        "next_scheduled_at": (
            futuro.proximo.isoformat() if futuro and futuro.proximo else None
        ),
        "server_time": now.isoformat(),
    }


class ReleaseIn(BaseModel):
    batch_id: str | None = None


@router.post("/queue/release")
def release_scheduled_endpoint(
    body: ReleaseIn | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require(Role.ADMINISTRATOR)),
    queue: str | None = Query(default="discovery"),
) -> dict:
    """Antecipa para AGORA os jobs pendentes agendados para o futuro (ex.: esperando o
    reset da franquia de uma conta que você já trocou). Opcionalmente só de uma campanha."""
    batch = body.batch_id if body else None
    try:
        ids = release_scheduled(db, queue=queue or None, batch_id=batch)
    except ProgrammingError:
        db.rollback()
        return {"released": 0, "schema_missing": True}
    return {"released": len(ids)}


@router.post("/queue/{job_id}/cancel")
def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    """Cancela um job ainda pendente (`todo`). Jobs em execução não são interrompidos:
    o run do harness segue até o fim e fica registrado em /discovery/runs."""
    try:
        atual = db.execute(
            text("select status::text as status from procrastinate_jobs where id = :id"),
            {"id": job_id},
        ).first()
    except ProgrammingError:
        db.rollback()
        raise NotFoundError("Fila indisponível: schema do procrastinate não aplicado") from None
    if atual is None:
        raise NotFoundError(f"Job {job_id} não encontrado")
    if atual.status != "todo":
        raise InvalidTransitionError(
            f"Job {job_id} está '{atual.status}'; só jobs pendentes (todo) podem ser cancelados"
        )
    db.execute(_CANCEL_SQL, {"id": job_id})
    db.commit()
    return {"id": job_id, "status": "cancelled"}


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
