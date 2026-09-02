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
