"""Notificações in-app (PRD §73)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.kernel.errors import NotFoundError
from app.models.auth import User
from app.models.review import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc()).limit(100)).all()
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read.is_(False))
    )
    return {
        "unread": unread,
        "items": [
            {
                "id": str(n.id),
                "type": n.type,
                "atom_id": n.atom_id,
                "message": n.message,
                "read": n.read,
                "at": n.created_at.isoformat(),
            }
            for n in rows
        ],
    }


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise NotFoundError("Notificação não encontrada")
    n.read = True
    db.commit()
    return {"id": str(n.id), "read": True}


@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    rows = db.scalars(
        select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))
    ).all()
    for n in rows:
        n.read = True
    db.commit()
    return {"marked": len(rows)}
