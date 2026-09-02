import logging

import procrastinate

from app.config import settings

log = logging.getLogger(__name__)


def _pg_conninfo(url: str) -> str:
    """Converte a URL SQLAlchemy (postgresql+psycopg://) para conninfo psycopg puro."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


job_app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=_pg_conninfo(settings.database_url))
)


@job_app.task(name="jobs.ping")
def ping() -> str:
    return "pong"


@job_app.task(name="jobs.export_canonical")
def export_canonical_job(trigger: str = "event") -> dict:
    """Export reconciliador: sincroniza o canonical-repo com o banco (D3).

    Idempotente — qualquer gatilho perdido converge no próximo export.
    """
    from app.canonical.exporter import export_canonical
    from app.db import SessionLocal

    with SessionLocal() as db:
        return export_canonical(db, settings.canonical_repo_path, trigger=trigger)


@job_app.task(name="jobs.run_discovery", queue="discovery")
def run_discovery_job(
    source_id: str,
    agent: str,
    domain: str,
    capability: str | None = None,
    actor: str = "system:scheduler",
    scope_hint: str = "todo o repositório",
    budget_usd: float = 5.0,
) -> dict:
    """Discovery na fila `discovery` — consumida APENAS por worker no host
    (o container não tem o CLI `claude`). Limite de franquia → reagenda em 30min.
    """
    import uuid as _uuid

    from app.db import SessionLocal
    from app.services.discovery import run_corroboration, run_discovery

    with SessionLocal() as db:
        kwargs = dict(
            source_id=_uuid.UUID(source_id), domain=domain, capability=capability,
            actor=actor, budget_usd=budget_usd,
        )
        if agent == "corroboration":
            run = run_corroboration(db, **kwargs)
        else:
            run = run_discovery(db, agent=agent, scope_hint=scope_hint, **kwargs)
        if run.status == "limit":
            run_discovery_job.configure(schedule_in={"seconds": 1800}).defer(
                source_id=source_id, agent=agent, domain=domain, capability=capability,
                actor=actor, scope_hint=scope_hint, budget_usd=budget_usd,
            )
        if run.status == "succeeded":
            defer_export(trigger=f"discovery:{run.id}")
        return {
            "run_id": str(run.id), "status": run.status,
            "candidates": run.candidates_created, "cost_usd": run.cost_usd,
        }


def defer_export(trigger: str) -> bool:
    """Best-effort pós-commit; o queueing lock garante no máximo 1 export na fila."""
    job = export_canonical_job.configure(queueing_lock="canonical-export")
    try:
        try:
            job.defer(trigger=trigger)
        except procrastinate.exceptions.AppNotOpen:
            with job_app.open():
                job.defer(trigger=trigger)
        return True
    except procrastinate.exceptions.AlreadyEnqueued:
        return True  # já existe um export pendente que cobrirá este gatilho
    except Exception:
        log.warning("defer do export canônico falhou (reconciliação cobrirá)", exc_info=True)
        return False
