"""Inventário de fontes: que arquivos existem na Source e a que capabilities se ligam.

Produzido pelo agente `inventory` (em lotes) e consumido pelo discovery dirigido, que
abre um turno por arquivo (ou por faixa de linhas) por capability.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("source_id", "path", name="uq_source_files_source_path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    path: Mapped[str] = mapped_column(String(1000))  # relativo ao workspace, separador '/'
    language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lines: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    # o que o arquivo faz, em termos de negócio
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    inventoried_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SourceFileCapability(Base):
    __tablename__ = "source_file_capabilities"
    __table_args__ = (
        UniqueConstraint("file_id", "capability_slug", name="uq_source_file_capability"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), index=True
    )
    capability_slug: Mapped[str] = mapped_column(ForeignKey("capabilities.slug"), index=True)
    # 1 tangencial · 2 relevante · 3 central
    relevance: Mapped[int] = mapped_column(Integer, default=2)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CapabilitySuggestion(Base):
    """Capability que o inventário achou no código mas não existe no cadastro do domain."""

    __tablename__ = "capability_suggestions"
    __table_args__ = (
        UniqueConstraint("source_id", "domain_slug", "name", name="uq_capability_suggestion"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    domain_slug: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    example_files: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    hits: Mapped[int] = mapped_column(Integer, default=1)  # quantos lotes sugeriram
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
