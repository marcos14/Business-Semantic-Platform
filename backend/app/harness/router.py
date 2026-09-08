"""API do executor remoto.

Lado dos agentes (`X-BSP-Agent-Key`): registro, claim, heartbeat, resultado, falha.
Lado da plataforma (JWT): status, registro de agentes (admin cria/rotaciona/revoga),
tarefas e cancelamento.
"""

import secrets
import socket
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.harness import service
from app.harness.auth import credential_hash, get_current_agent
from app.models.auth import Role, User
from app.models.harness import HarnessAgent, HarnessTask
from app.rbac.deps import require

router = APIRouter(prefix="/harness", tags=["harness"])


# ---------- lado dos agentes ----------


class AgentHello(BaseModel):
    agent_version: str = Field(min_length=1, max_length=40)
    cli_version: str | None = Field(default=None, max_length=100)
    host: str | None = Field(default=None, max_length=200)
    state: str | None = Field(default=None, max_length=20)  # idle | busy | paused
    # Sources que esta máquina consegue clonar; None = qualquer uma.
    sources: list[uuid.UUID] | None = None


def _hello(db: Session, agent: HarnessAgent, body: AgentHello) -> None:
    if not service.version_ok(body.agent_version):
        raise HTTPException(
            status.HTTP_426_UPGRADE_REQUIRED,
            f"Agente {body.agent_version} desatualizado: mínimo "
            f"{settings.harness_min_agent_version}. Atualize o bsp-agent.",
        )
    agent.agent_version = body.agent_version
    if body.cli_version:
        agent.cli_version = body.cli_version
    if body.host:
        agent.host = body.host
    if body.state in ("idle", "busy", "paused"):
        agent.state = body.state
    db.commit()


def _agent_settings() -> dict:
    return {
        "protocol": service.PROTOCOL_VERSION,
        "min_agent_version": settings.harness_min_agent_version,
        "executor": settings.harness_executor,
        "lease_seconds": settings.harness_task_lease_seconds,
        "heartbeat_seconds": max(15, settings.harness_task_lease_seconds // 3),
        "poll_seconds": max(5, int(settings.harness_poll_seconds * 5)),
        "log_max_chars": settings.harness_log_max_chars,
    }


@router.post("/agent/register")
def agent_register(
    body: AgentHello,
    db: Session = Depends(get_db),
    agent: HarnessAgent = Depends(get_current_agent),
) -> dict:
    _hello(db, agent, body)
    return {
        "agent_id": str(agent.id),
        "name": agent.name,
        "server": socket.gethostname(),
        **_agent_settings(),
    }


@router.post("/agent/claim")
def agent_claim(
    body: AgentHello,
    response: Response,
    db: Session = Depends(get_db),
    agent: HarnessAgent = Depends(get_current_agent),
) -> dict | None:
    """Arrenda a próxima tarefa. 204 = nada a fazer (fila vazia ou agente limitado)."""
    _hello(db, agent, body)
    if body.state == "paused":
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    task = service.claim_task(db, agent, body.sources)
    if task is None:
        if agent.state == "busy":
            agent.state = "idle"
            db.commit()
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return {
        "task_id": str(task.id),
        "attempt": task.attempts,
        "max_attempts": task.max_attempts,
        "lease_expires_at": task.lease_expires_at.isoformat(),
        "heartbeat_seconds": _agent_settings()["heartbeat_seconds"],
        "packet": task.packet,
    }


def _task_or_404(db: Session, task_id: uuid.UUID) -> HarnessTask:
    task = db.get(HarnessTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tarefa inexistente")
    return task


@router.post("/agent/tasks/{task_id}/heartbeat")
def agent_heartbeat(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    agent: HarnessAgent = Depends(get_current_agent),
) -> dict:
    task = _task_or_404(db, task_id)
    try:
        return service.heartbeat(db, task, agent)
    except service.OwnershipError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None


class ResultIn(BaseModel):
    result: dict
    log_text: str | None = None


@router.post("/agent/tasks/{task_id}/result")
def agent_result(
    task_id: uuid.UUID,
    body: ResultIn,
    db: Session = Depends(get_db),
    agent: HarnessAgent = Depends(get_current_agent),
) -> dict:
    task = _task_or_404(db, task_id)
    if task.status in service.TERMINAL:
        # resultado atrasado de um lease vencido: registra o custo, não ingere de novo
        service._add_cost(agent, float(body.result.get("cost_usd") or 0.0), datetime.now(UTC))
        db.commit()
        return {"outcome": "ignored", "status": task.status}
    try:
        return service.complete_task(db, task, agent, body.result, body.log_text)
    except service.OwnershipError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None


class FailIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)  # workspace | rate_limit | exception | ...
    detail: str = Field(default="", max_length=4000)


@router.post("/agent/tasks/{task_id}/fail")
def agent_fail(
    task_id: uuid.UUID,
    body: FailIn,
    db: Session = Depends(get_db),
    agent: HarnessAgent = Depends(get_current_agent),
) -> dict:
    task = _task_or_404(db, task_id)
    if task.status in service.TERMINAL:
        return {"outcome": "ignored", "status": task.status}
    try:
        return service.fail_task(db, task, agent, body.kind, body.detail)
    except service.OwnershipError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None


# ---------- lado da plataforma ----------


@router.get("/status")
def harness_status(
    db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> dict:
    agora = datetime.now(UTC)
    agentes = db.scalars(select(HarnessAgent).where(HarnessAgent.active.is_(True))).all()
    por_status: dict[str, int] = {}
    for a in agentes:
        s = service.agent_status(a, agora)
        por_status[s] = por_status.get(s, 0) + 1
    return {
        "executor": settings.harness_executor,
        "min_agent_version": settings.harness_min_agent_version,
        "agents": {
            "total": len(agentes),
            "online": sum(por_status.get(k, 0) for k in ("idle", "busy", "limited", "paused")),
            **por_status,
        },
        "tasks": service.task_counts(db),
        "server_time": agora.isoformat(),
    }


@router.get("/agents")
def list_agents(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    include_revoked: bool = False,
) -> list[dict]:
    agora = datetime.now(UTC)
    stmt = select(HarnessAgent).order_by(HarnessAgent.name)
    if not include_revoked:
        stmt = stmt.where(HarnessAgent.active.is_(True))
    return [service.agent_out(db, a, agora) for a in db.scalars(stmt)]


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    user_id: uuid.UUID


@router.post("/agents", status_code=status.HTTP_201_CREATED)
def create_agent(
    body: AgentIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    """Cria a credencial de um agente. A chave completa só aparece nesta resposta."""
    alvo = db.get(User, body.user_id)
    if alvo is None or not alvo.active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Usuário inexistente ou inativo")
    secret = secrets.token_urlsafe(32)
    agent = HarnessAgent(
        name=body.name.strip(),
        client_id=f"hag_{secrets.token_urlsafe(12)}",
        secret_hash=credential_hash(secret),
        user_id=body.user_id,
        created_by=admin.email,
    )
    db.add(agent)
    db.commit()
    return {**service.agent_out(db, agent), "api_key": f"{agent.client_id}.{secret}"}


@router.post("/agents/{agent_id}/rotate")
def rotate_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    agent = db.get(HarnessAgent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agente inexistente")
    secret = secrets.token_urlsafe(32)
    agent.secret_hash = credential_hash(secret)
    agent.active = True
    db.commit()
    return {**service.agent_out(db, agent), "api_key": f"{agent.client_id}.{secret}"}


@router.delete("/agents/{agent_id}")
def revoke_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    agent = db.get(HarnessAgent, agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agente inexistente")
    agent.active = False
    agent.state = "offline"
    # tarefas que este agente segurava voltam para a fila
    for t in db.scalars(
        select(HarnessTask).where(
            HarnessTask.lease_agent_id == agent.id, HarnessTask.status == "leased"
        )
    ):
        service._requeue(t, reason=f"agente {agent.name} revogado")
    db.commit()
    return {"id": str(agent.id), "active": False}


@router.get("/tasks")
def list_tasks(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict]:
    stmt = select(HarnessTask).order_by(HarnessTask.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(HarnessTask.status.in_(status_filter.split(",")))
    return [service.task_out(t) for t in db.scalars(stmt)]


@router.get("/tasks/{task_id}")
def get_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return service.task_out(_task_or_404(db, task_id), with_packet=True)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require(Role.ADMINISTRATOR)),
) -> dict:
    task = _task_or_404(db, task_id)
    service.cancel_task(db, task, f"cancelada por {admin.email}")
    return service.task_out(task)
