import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(enum.StrEnum):
    """Papéis do PRD §7."""

    VIEWER = "viewer"
    REVIEWER = "reviewer"
    DOMAIN_EXPERT = "domain_expert"
    DECISION_OWNER = "decision_owner"
    ADMINISTRATOR = "administrator"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    bindings: Mapped[list["RoleBinding"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Domain(Base):
    __tablename__ = "domains"

    slug: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class Capability(Base):
    __tablename__ = "capabilities"

    slug: Mapped[str] = mapped_column(String(100), primary_key=True)
    domain_slug: Mapped[str] = mapped_column(ForeignKey("domains.slug"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # O que esta capability cobre em linguagem de negócio — orienta o inventário e o
    # discovery dirigido (o agente recebe isto no prompt).
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class RoleBinding(Base):
    """Papel escopado (PRD §103): domain/capability nulos = binding global para aquele papel."""

    __tablename__ = "role_bindings"
    __table_args__ = (
        UniqueConstraint("user_id", "role", "domain_slug", "capability_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", values_callable=lambda e: [m.value for m in e])
    )
    domain_slug: Mapped[str | None] = mapped_column(ForeignKey("domains.slug"), nullable=True)
    capability_slug: Mapped[str | None] = mapped_column(
        ForeignKey("capabilities.slug"), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="bindings")
