import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Enums de status/kind/etc. são String no banco (validação no kernel):
# adicionar um kind novo não exige ALTER TYPE (NFR de extensibilidade).


def _now() -> datetime:
    return datetime.now(UTC)


class Source(Base):
    """Source Registry (PRD §10)."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    repository: Mapped[str | None] = mapped_column(String(500), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    domain_slug: Mapped[str | None] = mapped_column(ForeignKey("domains.slug"), nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_by: Mapped[str] = mapped_column(String(320))


class KnowledgeAtom(Base):
    """Envelope comum (PRD §14) em colunas + body específico do kind em JSONB."""

    __tablename__ = "knowledge_atoms"
    __table_args__ = (
        Index("ix_knowledge_atoms_search", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(300), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str] = mapped_column(ForeignKey("domains.slug"), index=True)
    capability: Mapped[str | None] = mapped_column(
        ForeignKey("capabilities.slug"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), index=True)
    classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Relevância de negócio (Significance): TRIVIAL nunca é gravado; LOW não vai a humano.
    significance: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    effective: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    body: Mapped[dict] = mapped_column(JSONB, default=dict)
    origin: Mapped[str] = mapped_column(String(10))  # agent | human
    version: Mapped[int] = mapped_column(Integer, default=1)  # versão canônica (§71)
    lock_version: Mapped[int] = mapped_column(Integer, default=0)  # optimistic locking (§105)
    # §56: importância estrutural no graph (0..1, centralidade normalizada; job periódico)
    centrality: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Full-text search (§53): coluna gerada sobre title + description + statement
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('portuguese', coalesce(title,'') || ' ' || "
            "coalesce(description,'') || ' ' || coalesce(body->>'statement',''))",
            persisted=True,
        ),
        nullable=True,
    )
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    evidence_links: Mapped[list["EvidenceLink"]] = relationship(
        back_populates="atom", cascade="all, delete-orphan"
    )


class KnowledgeAtomVersion(Base):
    """Snapshot imutável a cada mutação — histórico nunca é destruído (§71)."""

    __tablename__ = "knowledge_atom_versions"
    __table_args__ = (UniqueConstraint("atom_id", "rev"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    atom_id: Mapped[str] = mapped_column(ForeignKey("knowledge_atoms.id"), index=True)
    rev: Mapped[int] = mapped_column(Integer)  # lock_version no momento do snapshot
    version: Mapped[int] = mapped_column(Integer)  # versão canônica vigente
    snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_by: Mapped[str] = mapped_column(String(320))


class Evidence(Base):
    """PRD §23 — evidência é entidade própria, referenciável por vários atoms."""

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(30), index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    location: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # tradução amigável (§46)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)  # trecho técnico
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    origin: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EvidenceLink(Base):
    """Vínculo atom↔evidence; relation distingue suporte de contradição (§39, §74)."""

    __tablename__ = "evidence_links"

    atom_id: Mapped[str] = mapped_column(ForeignKey("knowledge_atoms.id"), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence.id"), primary_key=True)
    relation: Mapped[str] = mapped_column(String(20), default="supports")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    atom: Mapped[KnowledgeAtom] = relationship(back_populates="evidence_links")
    evidence: Mapped[Evidence] = relationship()


class AtomRelation(Base):
    """Edges do graph semântico (§54) — o graph é projeção desta tabela."""

    __tablename__ = "atom_relations"
    __table_args__ = (UniqueConstraint("from_atom", "to_atom", "type"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    from_atom: Mapped[str] = mapped_column(ForeignKey("knowledge_atoms.id"), index=True)
    to_atom: Mapped[str] = mapped_column(ForeignKey("knowledge_atoms.id"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    created_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DomainEvent(Base):
    """Log append-only (§98). É o audit trail (§69-§70) por construção."""

    __tablename__ = "domain_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    atom_id: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(320))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
