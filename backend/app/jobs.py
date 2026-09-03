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
        _reagenda_se_limite(
            run, run_discovery_job,
            source_id=source_id, agent=agent, domain=domain, capability=capability,
            actor=actor, scope_hint=scope_hint, budget_usd=budget_usd,
        )
        if run.status == "succeeded":
            defer_export(trigger=f"discovery:{run.id}")
        return {
            "run_id": str(run.id), "status": run.status,
            "candidates": run.candidates_created, "cost_usd": run.cost_usd,
        }


RESET_DEFAULT_SECONDS = 1800
RESET_MAX_SECONDS = 6 * 3600


def delay_until_reset(texto: str | None, agora=None) -> int:
    """Segundos até o reset da franquia, lidos da mensagem do harness
    ("You've hit your session limit · resets 10:30pm (America/Sao_Paulo)").
    Sem horário reconhecível → 30min. Evita o ciclo de tentar a cada 30min e
    bater no limite de novo (cada tentativa vira um run 'limit' na auditoria)."""
    import re
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    if not texto:
        return RESET_DEFAULT_SECONDS
    m = re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", texto, re.I)
    if not m:
        return RESET_DEFAULT_SECONDS
    hora, minuto, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ampm == "pm" and hora < 12:
        hora += 12
    if ampm == "am" and hora == 12:
        hora = 0
    tz = None
    mtz = re.search(r"\(([A-Za-z_]+/[A-Za-z_]+)\)", texto)
    if mtz:
        try:
            tz = ZoneInfo(mtz.group(1))
        except Exception:
            tz = None
    agora = agora or datetime.now(tz)
    if tz is not None and agora.tzinfo is not None:
        agora = agora.astimezone(tz)
    alvo = agora.replace(hour=hora % 24, minute=minuto, second=0, microsecond=0)
    if alvo <= agora:
        alvo += timedelta(days=1)
    delta = int((alvo - agora).total_seconds()) + 60  # folga de 1min após o reset
    return max(60, min(delta, RESET_MAX_SECONDS))


def _reagenda_se_limite(run, task, **kwargs) -> None:
    """Franquia esgotada → mesmo job de novo quando a franquia resetar."""
    if run.status == "limit":
        segundos = delay_until_reset(run.error)
        log.info("franquia esgotada: reagendando %s em %ds", task.name, segundos)
        task.configure(schedule_in={"seconds": segundos}).defer(**kwargs)


def inventory_batch_kwargs(
    db,
    *,
    source_id: str,
    domain: str,
    prefix: str | None,
    max_files: int | None,
    only_missing: bool,
    actor: str,
    batch_id: str,
    budget_usd: float,
) -> list[dict]:
    """Planeja os lotes do inventário (lê o repositório) e devolve os kwargs de um
    `run_inventory_job` por lote. Roda NO HOST: a API em container não vê o disco."""
    import uuid as _uuid

    from app.models.knowledge import Source
    from app.services.inventory import plan_inventory

    src = db.get(Source, _uuid.UUID(source_id))
    if src is None:
        return []
    lotes, _ = plan_inventory(
        db, src, prefix=prefix, max_files=max_files, only_missing=only_missing
    )
    return [
        dict(source_id=source_id, domain=domain, files=lote, actor=actor,
             batch_id=batch_id, budget_usd=budget_usd)
        for lote in lotes
    ]


@job_app.task(name="jobs.plan_inventory", queue="discovery")
def plan_inventory_job(
    source_id: str,
    domain: str,
    prefix: str | None = None,
    max_files: int | None = None,
    only_missing: bool = True,
    actor: str = "system:scheduler",
    batch_id: str | None = None,
    budget_usd: float = 3.0,
) -> dict:
    """Fan-out do inventário: enumera os fontes no host e enfileira um job por lote."""
    import uuid as _uuid

    from app.db import SessionLocal

    batch_id = batch_id or str(_uuid.uuid4())
    with SessionLocal() as db:
        lotes = inventory_batch_kwargs(
            db, source_id=source_id, domain=domain, prefix=prefix, max_files=max_files,
            only_missing=only_missing, actor=actor, batch_id=batch_id, budget_usd=budget_usd,
        )
    for kw in lotes:
        run_inventory_job.defer(**kw)
    total = sum(len(kw["files"]) for kw in lotes)
    log.info(
        "inventário %s: %d arquivo(s) em %d lote(s) enfileirado(s)", batch_id, total, len(lotes)
    )
    return {"batch_id": batch_id, "files": total, "jobs": len(lotes)}


@job_app.task(name="jobs.run_inventory", queue="discovery")
def run_inventory_job(
    source_id: str,
    domain: str,
    files: list[str],
    actor: str = "system:scheduler",
    batch_id: str | None = None,
    budget_usd: float = 3.0,
) -> dict:
    """Um lote do inventário de fontes (fila `discovery`, worker no host)."""
    import uuid as _uuid

    from app.db import SessionLocal
    from app.services.inventory import run_inventory_batch

    kwargs = dict(
        source_id=source_id, domain=domain, files=files, actor=actor,
        batch_id=batch_id, budget_usd=budget_usd,
    )
    with SessionLocal() as db:
        run = run_inventory_batch(
            db, source_id=_uuid.UUID(source_id), domain=domain, files=files, actor=actor,
            batch_id=_uuid.UUID(batch_id) if batch_id else None, budget_usd=budget_usd,
        )
        _reagenda_se_limite(run, run_inventory_job, **kwargs)
        return {
            "run_id": str(run.id), "status": run.status,
            "files": run.candidates_created, "cost_usd": run.cost_usd,
        }


@job_app.task(name="jobs.run_directed", queue="discovery")
def run_directed_job(
    source_id: str,
    domain: str,
    capability: str,
    file: str,
    start_line: int = 1,
    end_line: int | None = None,
    actor: str = "system:scheduler",
    batch_id: str | None = None,
    budget_usd: float = 3.0,
    max_candidates: int = 12,
    is_followup: bool = False,
) -> dict:
    """Um turno do discovery dirigido: arquivo (faixa) × capability. Follow-ups pedidos
    pelo agente entram na mesma campanha, até `discovery_followups_max` por batch."""
    import uuid as _uuid

    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models.discovery import DiscoveryRun
    from app.services.discovery import run_directed_discovery

    kwargs = dict(
        source_id=source_id, domain=domain, capability=capability, file=file,
        start_line=start_line, end_line=end_line, actor=actor, batch_id=batch_id,
        budget_usd=budget_usd, max_candidates=max_candidates, is_followup=is_followup,
    )
    bid = _uuid.UUID(batch_id) if batch_id else None
    with SessionLocal() as db:
        run = run_directed_discovery(
            db, source_id=_uuid.UUID(source_id), domain=domain, capability=capability,
            file=file, start_line=start_line, end_line=end_line, actor=actor, batch_id=bid,
            is_followup=is_followup, budget_usd=budget_usd, max_candidates=max_candidates,
        )
        _reagenda_se_limite(run, run_directed_job, **kwargs)
        enfileirados = 0
        if run.status == "succeeded":
            defer_export(trigger=f"discovery:{run.id}")
            for fu in getattr(run, "followups", []) or []:
                if bid is None:
                    break
                ja_tem = db.scalar(
                    select(func.count()).select_from(DiscoveryRun).where(
                        DiscoveryRun.batch_id == bid, DiscoveryRun.target_file == fu["file"]
                    )
                )
                n_followups = db.scalar(
                    select(func.count()).select_from(DiscoveryRun).where(
                        DiscoveryRun.batch_id == bid, DiscoveryRun.line_range.like("f:%")
                    )
                )
                if ja_tem or (n_followups or 0) + enfileirados >= settings.discovery_followups_max:
                    continue
                run_directed_job.defer(
                    **{**kwargs, "file": fu["file"], "start_line": fu["start_line"],
                       "end_line": fu["end_line"], "is_followup": True}
                )
                enfileirados += 1
        return {
            "run_id": str(run.id), "status": run.status, "file": file,
            "candidates": run.candidates_created, "cost_usd": run.cost_usd,
            "followups_enqueued": enfileirados,
        }


@job_app.periodic(cron="*/30 * * * *")
@job_app.task(name="jobs.compute_centrality")
def compute_centrality_job(timestamp: int | None = None) -> dict:
    """§56: recalcula a importância estrutural do graph (alimenta a priorização §84)."""
    from app.db import SessionLocal
    from app.services.graph import compute_centrality

    with SessionLocal() as db:
        n = compute_centrality(db)
        db.commit()
    return {"atoms": n}


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
