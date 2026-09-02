"""Notificações in-app (§73), criadas na mesma transação da mutação que as gera."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.auth import Role, RoleBinding, User
from app.models.review import Notification

# Papéis que implicam autoridade de decisão em um escopo
_OWNER_ROLES = (Role.DECISION_OWNER, Role.ADMINISTRATOR)
# Papéis que implicam capacidade de revisar
_REVIEWER_ROLES = (
    Role.REVIEWER,
    Role.DOMAIN_EXPERT,
    Role.DECISION_OWNER,
    Role.ADMINISTRATOR,
)


def notify(
    db: Session,
    user_ids: set[uuid.UUID],
    *,
    type: str,
    message: str,
    atom_id: str | None = None,
    exclude_user_id: uuid.UUID | None = None,
) -> int:
    n = 0
    for uid in user_ids:
        if uid == exclude_user_id:
            continue
        db.add(Notification(user_id=uid, type=type, message=message[:500], atom_id=atom_id))
        n += 1
    return n


def _scoped_user_ids(
    db: Session, roles: tuple[Role, ...], domain: str, capability: str | None
) -> set[uuid.UUID]:
    stmt = (
        select(RoleBinding.user_id)
        .where(RoleBinding.role.in_(roles))
        .where(or_(RoleBinding.domain_slug.is_(None), RoleBinding.domain_slug == domain))
        .where(
            or_(
                RoleBinding.capability_slug.is_(None),
                RoleBinding.capability_slug == capability,
            )
        )
    )
    return set(db.scalars(stmt))


def notify_reviewers(
    db: Session, atom, *, type: str, message: str, exclude_user_id: uuid.UUID | None = None
) -> int:
    ids = _scoped_user_ids(db, _REVIEWER_ROLES, atom.domain, atom.capability)
    return notify(
        db, ids, type=type, message=message, atom_id=atom.id, exclude_user_id=exclude_user_id
    )


def notify_owners(
    db: Session, atom, *, type: str, message: str, exclude_user_id: uuid.UUID | None = None
) -> int:
    ids = _scoped_user_ids(db, _OWNER_ROLES, atom.domain, atom.capability)
    return notify(
        db, ids, type=type, message=message, atom_id=atom.id, exclude_user_id=exclude_user_id
    )


def notify_mentions(db: Session, atom, text: str, *, author_id: uuid.UUID) -> int:
    """§73: 'Comment mentions user' — menção por e-mail no texto."""
    mencionados = {
        u.id
        for u in db.scalars(select(User))
        if u.email in text.lower() and u.id != author_id
    }
    return notify(
        db,
        mencionados,
        type="mention",
        message=f"Você foi mencionado em {atom.id}: {text[:120]}",
        atom_id=atom.id,
    )
