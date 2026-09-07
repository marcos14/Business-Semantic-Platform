import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class HelpDeskPolicy(Base):
    """Política de exposição do conhecimento para um perfil consumidor."""

    __tablename__ = "helpdesk_policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    consumer_profile: Mapped[str] = mapped_column(String(40), index=True)
    scope_type: Mapped[str] = mapped_column(String(30), default="global")
    selector: Mapped[str | None] = mapped_column(String(200), nullable=True)
    allowed_statuses: Mapped[list] = mapped_column(JSONB, default=list)
    minimum_confidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    allow_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_conflicted: Mapped[bool] = mapped_column(Boolean, default=False)
    critical_requires_escalation: Mapped[bool] = mapped_column(Boolean, default=True)
    include_evidence_excerpt: Mapped[bool] = mapped_column(Boolean, default=False)
    include_internal_location: Mapped[bool] = mapped_column(Boolean, default=False)
    max_context_tokens: Mapped[int] = mapped_column(Integer, default=8000)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class HelpDeskClientCredential(Base):
    """Credencial rotacionável de uma aplicação consumidora, vinculada a um usuário RBAC."""

    __tablename__ = "helpdesk_client_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    client_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    allowed_profiles: Mapped[list] = mapped_column(JSONB, default=list)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    rate_window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class HelpDeskInteraction(Base):
    """Snapshot auditável do conhecimento entregue a um consumidor."""

    __tablename__ = "helpdesk_interactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    consumer: Mapped[str] = mapped_column(String(320), index=True)
    consumer_profile: Mapped[str] = mapped_column(String(40), index=True)
    question_hash: Mapped[str] = mapped_column(String(64), index=True)
    # Redação mínima para investigação; integrações podem enviar apenas texto já anonimizado.
    question_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_context: Mapped[dict] = mapped_column(JSONB, default=dict)
    resolved_context: Mapped[dict] = mapped_column(JSONB, default=dict)
    policy_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    knowledge_refs: Mapped[list] = mapped_column(JSONB, default=list)
    answerability: Mapped[str] = mapped_column(String(30), index=True)
    recommended_action: Mapped[str] = mapped_column(String(30), index=True)
    retrieval_version: Mapped[str] = mapped_column(String(30))
    knowledge_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    budget: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class HelpDeskFeedback(Base):
    """Resultado operacional; não muda confiança/canonical automaticamente."""

    __tablename__ = "helpdesk_feedback"
    __table_args__ = (UniqueConstraint("interaction_id", "idempotency_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    interaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("helpdesk_interactions.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(30), index=True)
    helpful_atom_ids: Mapped[list] = mapped_column(JSONB, default=list)
    misleading_atom_ids: Mapped[list] = mapped_column(JSONB, default=list)
    missing_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticket_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class EvidenceFreshness(Base):
    """Última comparação de uma evidência com o HEAD conhecido de sua Source."""

    __tablename__ = "evidence_freshness"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(30), index=True)
    source_head_commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
