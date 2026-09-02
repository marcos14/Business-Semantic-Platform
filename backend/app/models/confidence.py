import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class ConfidenceScore(Base):
    """Score calculado — append-only: recalcular NUNCA reescreve histórico (§27, P4)."""

    __tablename__ = "confidence_scores"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    atom_id: Mapped[str] = mapped_column(ForeignKey("knowledge_atoms.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    engine_version: Mapped[str] = mapped_column(String(20))
    trigger: Mapped[str] = mapped_column(String(60))
    actor: Mapped[str] = mapped_column(String(320))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    signals: Mapped[list["ConfidenceSignal"]] = relationship(
        back_populates="score_row", cascade="all, delete-orphan"
    )


class ConfidenceSignal(Base):
    """Sinais do §28 como fatos, presos ao score que os usou (explicabilidade §30)."""

    __tablename__ = "confidence_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    score_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("confidence_scores.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    value: Mapped[float] = mapped_column(Float)
    contribution: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(String(300))

    score_row: Mapped[ConfidenceScore] = relationship(back_populates="signals")


class Policy(Base):
    """Políticas como dados (§32-§35). Resolução/precedência em app.kernel.policy."""

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    scope_type: Mapped[str] = mapped_column(String(20))  # global|domain|atom_kind|capability|risk
    selector: Mapped[str | None] = mapped_column(String(200), nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    human_review_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    min_reviewers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    require_owner_approval: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
