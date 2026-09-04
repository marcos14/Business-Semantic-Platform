"""Embedding por atom (pgvector), em tabela própria: permite re-embedar ao trocar de modelo
sem tocar em knowledge_atoms e mantém o índice HNSW isolado."""

from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class AtomEmbedding(Base):
    __tablename__ = "atom_embeddings"

    atom_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_atoms.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(100))
    text_hash: Mapped[str] = mapped_column(String(32))  # do texto embedado (statement/título)
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
