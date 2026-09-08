"""Execução remota do harness (opcional, `HARNESS_EXECUTOR=remote`).

Agentes são máquinas de membros da equipe que rodam `claude -p` com a própria chave de
API. O servidor continua dono de tudo o que toca o banco: monta o prompt, publica a
chamada como uma `HarnessTask` fechada e ingere o resultado. O agente só executa.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class HarnessAgent(Base):
    """Credencial rotacionável de um agente remoto, vinculada a um usuário RBAC."""

    __tablename__ = "harness_agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    client_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Telemetria informada pelo próprio agente a cada registro/claim.
    host: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cli_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="offline")
    # idle | busy | paused | limited | offline (derivado do heartbeat na leitura)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    limited_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    limit_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    tasks_done: Mapped[int] = mapped_column(Integer, default=0)
    tasks_failed: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd_total: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd_today: Mapped[float] = mapped_column(Float, default=0.0)
    cost_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class HarnessTask(Base):
    """Uma chamada ao harness, pronta para qualquer agente executar.

    O pacote é fechado: prompt, schema, modelo, ferramentas e o commit que o agente deve
    ter no clone. O resultado volta no mesmo formato de `claude_code.RunResult`.
    """

    __tablename__ = "harness_tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discovery_runs.id"), nullable=True, index=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id"), nullable=True, index=True
    )
    label: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="ready", index=True)
    # ready | leased | succeeded | failed | cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    packet: Mapped[dict] = mapped_column(JSONB, default=dict)
    lease_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("harness_agents.id"), nullable=True, index=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
