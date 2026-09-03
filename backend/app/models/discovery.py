import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class DiscoveryRun(Base):
    """Auditoria de cada execução do harness (§87: versões de agente, custo, log)."""

    __tablename__ = "discovery_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    agent: Mapped[str] = mapped_column(String(30))  # code | test | corroboration | inventory
    status: Mapped[str] = mapped_column(String(20), default="running")
    # running | succeeded | failed | limit | auth_failed
    domain: Mapped[str] = mapped_column(String(100))
    capability: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Campanha (inventário em lotes / discovery dirigido arquivo a arquivo): agrupa os
    # muitos runs pequenos de um mesmo disparo.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    target_file: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    line_range: Mapped[str | None] = mapped_column(String(40), nullable=True)  # "1-1200"
    commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(50), default="opus")
    effort: Mapped[str] = mapped_column(String(20), default="high")
    cli_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    num_turns: Mapped[int] = mapped_column(Integer, default=0)
    candidates_created: Mapped[int] = mapped_column(Integer, default=0)
    candidates_rejected: Mapped[int] = mapped_column(Integer, default=0)
    questions_created: Mapped[int] = mapped_column(Integer, default=0)
    evidence_rejected: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_skipped: Mapped[int] = mapped_column(Integer, default=0)
    potential_duplicates: Mapped[int] = mapped_column(Integer, default=0)
    workspace_clean: Mapped[str | None] = mapped_column(String(10), nullable=True)  # yes|no
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(320))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
