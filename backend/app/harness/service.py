"""Regras do executor remoto, compartilhadas pela API (lado dos agentes) e pelo broker
(lado do worker): pacote, claim com lease, heartbeat, resultado, falhas e reatribuição.

Princípios:
- O agente só executa. Prompt, schema, commit e ferramentas vêm fechados no pacote.
- Limite de franquia e falha de login são do AGENTE, não da tarefa: a tarefa volta à fila
  na hora para outro agente e só aquele agente fica de fora até o reset.
- Lease com heartbeat: agente que some devolve a tarefa à fila sem intervenção.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.engines import claude_code
from app.models.auth import User
from app.models.harness import HarnessAgent, HarnessTask

PROTOCOL_VERSION = 1
TERMINAL = ("succeeded", "failed", "cancelled")
ONLINE_SECONDS = 120  # sem contato por mais que isso → offline
RATE_LIMIT_COOLDOWN_SECONDS = 60


class OwnershipError(Exception):
    """A tarefa não está arrendada para este agente."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ---------- versão e pacote ----------


def version_tuple(v: str | None) -> tuple[int, ...]:
    partes = []
    for p in (v or "0").split("."):
        digitos = "".join(ch for ch in p if ch.isdigit())
        partes.append(int(digitos or 0))
    return tuple(partes)


def version_ok(v: str | None) -> bool:
    return version_tuple(v) >= version_tuple(settings.harness_min_agent_version)


def packet_from_options(op: claude_code.RunOptions) -> dict:
    """Tudo o que o agente precisa, e nada que dependa do banco."""
    r = op.remote
    return {
        "protocol": PROTOCOL_VERSION,
        "label": op.label,
        "prompt": op.prompt,
        "schema": op.schema,
        "model": op.model,
        "effort": op.effort,
        "budget_usd": op.budget_usd,
        "timeout_min": op.timeout_min,
        "read_only": op.read_only,
        "tools": op.tools,
        "setting_sources": op.setting_sources,
        "source": None
        if r is None
        else {
            "id": r.source_id,
            "repository": r.repository,
            "git_url": r.git_url,
            "subdir": r.subdir,
            "commit": r.commit,
            "branch": r.branch,
        },
    }


def create_task(db: Session, op: claude_code.RunOptions) -> HarnessTask:
    r = op.remote
    task = HarnessTask(
        run_id=uuid.UUID(op.run_id) if op.run_id else None,
        source_id=uuid.UUID(r.source_id) if r is not None else None,
        label=op.label[:200],
        packet=packet_from_options(op),
        max_attempts=settings.harness_task_max_attempts,
    )
    db.add(task)
    db.commit()
    return task


# ---------- fila ----------


def _requeue(task: HarnessTask, *, reason: str) -> None:
    """Volta para a fila; sem tentativas restantes, falha de vez."""
    task.lease_agent_id = None
    task.lease_expires_at = None
    if task.attempts >= task.max_attempts:
        task.status = "failed"
        task.error = f"{reason}; tentativas esgotadas ({task.attempts}/{task.max_attempts})"
        task.finished_at = _now()
    else:
        task.status = "ready"
        task.error = reason


def sweep_leases(db: Session) -> int:
    """Leases vencidos (agente sem heartbeat) voltam para a fila."""
    agora = _now()
    vencidas = db.scalars(
        select(HarnessTask)
        .where(HarnessTask.status == "leased", HarnessTask.lease_expires_at < agora)
        .with_for_update(skip_locked=True)
    ).all()
    for t in vencidas:
        _requeue(t, reason="lease expirado: agente parou de enviar heartbeat")
    if vencidas:
        db.commit()
    return len(vencidas)


def claim_task(
    db: Session, agent: HarnessAgent, sources: list[uuid.UUID] | None
) -> HarnessTask | None:
    """Arrenda a tarefa `ready` mais antiga que este agente consegue servir."""
    sweep_leases(db)
    agora = _now()
    if agent.limited_until and _aware(agent.limited_until) > agora:
        return None
    stmt = select(HarnessTask).where(HarnessTask.status == "ready")
    if sources is not None:
        stmt = stmt.where(
            or_(HarnessTask.source_id.is_(None), HarnessTask.source_id.in_(sources))
        )
    task = db.scalars(
        stmt.order_by(HarnessTask.created_at).with_for_update(skip_locked=True).limit(1)
    ).first()
    if task is None:
        return None
    task.status = "leased"
    task.attempts += 1
    task.lease_agent_id = agent.id
    task.claimed_at = agora
    task.heartbeat_at = agora
    task.lease_expires_at = agora + timedelta(seconds=settings.harness_task_lease_seconds)
    task.error = None
    agent.state = "busy"
    db.commit()
    return task


def _check_owner(task: HarnessTask, agent: HarnessAgent) -> None:
    if task.lease_agent_id != agent.id or task.status != "leased":
        raise OwnershipError(
            f"tarefa {task.id} não está arrendada para este agente (status {task.status})"
        )


def heartbeat(db: Session, task: HarnessTask, agent: HarnessAgent) -> dict:
    if task.status == "leased":
        if task.lease_agent_id != agent.id:
            raise OwnershipError("tarefa arrendada para outro agente")
        agora = _now()
        task.heartbeat_at = agora
        task.lease_expires_at = agora + timedelta(seconds=settings.harness_task_lease_seconds)
        agent.state = "busy"
        db.commit()
    return {"status": task.status}


def _add_cost(agent: HarnessAgent, cost: float, agora: datetime) -> None:
    hoje = agora.date()
    if agent.cost_day != hoje:
        agent.cost_day = hoje
        agent.cost_usd_today = 0.0
    agent.cost_usd_today = float(agent.cost_usd_today or 0.0) + cost
    agent.cost_usd_total = float(agent.cost_usd_total or 0.0) + cost


def executed_by_label(db: Session, agent: HarnessAgent) -> str:
    user = db.get(User, agent.user_id)
    return f"{agent.name} <{user.email}>" if user else agent.name


def complete_task(
    db: Session,
    task: HarnessTask,
    agent: HarnessAgent,
    result: dict,
    log_text: str | None,
) -> dict:
    """O harness rodou no agente e devolveu um RunResult (sucesso OU erro do harness).

    Limite de franquia e login caído são tratados como indisponibilidade do agente: a
    tarefa volta para a fila e o agente fica marcado até o reset. Só quando as tentativas
    se esgotam o resultado é entregue como veio (o run vira `limit`/`auth_failed`, e o
    job é reagendado como no executor local).
    """
    _check_owner(task, agent)
    agora = _now()
    _add_cost(agent, float(result.get("cost_usd") or 0.0), agora)
    if result.get("cli_version"):
        agent.cli_version = str(result["cli_version"])[:100]
    agent.state = "idle"

    indisponivel = bool(result.get("session_limit") or result.get("auth_failed"))
    if indisponivel:
        agent.tasks_failed += 1
        if result.get("session_limit"):
            segundos = claude_code.delay_until_reset(result.get("limit_detail"))
            agent.limited_until = agora + timedelta(seconds=segundos)
            detalhe = result.get("limit_detail") or result.get("result_text") or ""
            agent.limit_detail = str(detalhe)[:500]
            agent.state = "limited"
            motivo = "limite de franquia no agente"
        else:
            agent.limit_detail = "harness deslogado ou chave inválida no agente"
            motivo = "falha de autenticação no agente"
        if task.attempts < task.max_attempts:
            _requeue(task, reason=f"{motivo} {agent.name}")
            db.commit()
            return {"outcome": "requeued", "status": task.status, "reason": motivo}

    task.status = "succeeded"
    task.result = result
    if log_text:
        task.log_text = log_text[: settings.harness_log_max_chars]
    task.executed_by = executed_by_label(db, agent)
    task.finished_at = agora
    task.error = None
    agent.tasks_done += 1
    db.commit()
    return {"outcome": "done", "status": task.status}


def fail_task(
    db: Session, task: HarnessTask, agent: HarnessAgent, kind: str, detail: str
) -> dict:
    """O agente NÃO conseguiu executar (clone, commit ausente, exceção, rate limit)."""
    _check_owner(task, agent)
    agora = _now()
    agent.tasks_failed += 1
    agent.state = "idle"
    if kind == "rate_limit":
        agent.limited_until = agora + timedelta(seconds=RATE_LIMIT_COOLDOWN_SECONDS)
        agent.limit_detail = (detail or "rate limit da API")[:500]
        agent.state = "limited"
    _requeue(task, reason=f"{kind} no agente {agent.name}: {(detail or '')[:500]}")
    db.commit()
    return {"outcome": task.status, "status": task.status}


def cancel_task(db: Session, task: HarnessTask, reason: str) -> None:
    if task.status in TERMINAL:
        return
    task.status = "cancelled"
    task.error = reason
    task.finished_at = _now()
    task.lease_expires_at = None
    db.commit()


# ---------- leitura ----------


def agent_status(agent: HarnessAgent, agora: datetime | None = None) -> str:
    agora = agora or _now()
    if not agent.active:
        return "revoked"
    visto = _aware(agent.last_seen_at)
    if visto is None or (agora - visto).total_seconds() > ONLINE_SECONDS:
        return "offline"
    if agent.limited_until and _aware(agent.limited_until) > agora:
        return "limited"
    return agent.state if agent.state in ("idle", "busy", "paused") else "idle"


def count_online_agents(db: Session) -> int:
    limite = _now() - timedelta(seconds=ONLINE_SECONDS)
    return int(
        db.scalar(
            select(func.count()).select_from(HarnessAgent).where(
                HarnessAgent.active.is_(True), HarnessAgent.last_seen_at >= limite
            )
        )
        or 0
    )


def agent_out(db: Session, agent: HarnessAgent, agora: datetime | None = None) -> dict:
    agora = agora or _now()
    user = db.get(User, agent.user_id)
    hoje = agent.cost_day == agora.date()
    gasto_hoje = float(agent.cost_usd_today or 0.0) if hoje else 0.0
    return {
        "id": str(agent.id),
        "name": agent.name,
        "client_id": agent.client_id,
        "user_id": str(agent.user_id),
        "user_email": user.email if user else None,
        "active": agent.active,
        "status": agent_status(agent, agora),
        "state": agent.state,
        "host": agent.host,
        "agent_version": agent.agent_version,
        "cli_version": agent.cli_version,
        "last_seen_at": agent.last_seen_at.isoformat() if agent.last_seen_at else None,
        "limited_until": agent.limited_until.isoformat() if agent.limited_until else None,
        "limit_detail": agent.limit_detail,
        "tasks_done": agent.tasks_done,
        "tasks_failed": agent.tasks_failed,
        "cost_usd_total": round(float(agent.cost_usd_total or 0.0), 4),
        "cost_usd_today": round(gasto_hoje, 4),
        "created_at": agent.created_at.isoformat(),
    }


def task_out(task: HarnessTask, *, with_packet: bool = False) -> dict:
    d = {
        "id": str(task.id),
        "run_id": str(task.run_id) if task.run_id else None,
        "source_id": str(task.source_id) if task.source_id else None,
        "label": task.label,
        "status": task.status,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "lease_agent_id": str(task.lease_agent_id) if task.lease_agent_id else None,
        "lease_expires_at": task.lease_expires_at.isoformat() if task.lease_expires_at else None,
        "claimed_at": task.claimed_at.isoformat() if task.claimed_at else None,
        "heartbeat_at": task.heartbeat_at.isoformat() if task.heartbeat_at else None,
        "executed_by": task.executed_by,
        "error": task.error,
        "created_at": task.created_at.isoformat(),
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "model": (task.packet or {}).get("model"),
        "commit": ((task.packet or {}).get("source") or {}).get("commit"),
        "cost_usd": float((task.result or {}).get("cost_usd") or 0.0),
    }
    if with_packet:
        d["packet"] = task.packet
    return d


def task_counts(db: Session) -> dict:
    rows = db.execute(
        select(HarnessTask.status, func.count()).group_by(HarnessTask.status)
    ).all()
    return {status: int(n) for status, n in rows}
