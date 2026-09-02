"""Bootstrap do primeiro administrador.

Uso: python -m app.create_admin <email> <nome> <senha>
Idempotente: se o usuário existir, garante o binding de administrator global.
"""

import sys

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.models.auth import Role, RoleBinding, User


def ensure_admin(email: str, name: str, password: str) -> User:
    email = email.lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name, password_hash=hash_password(password))
            db.add(user)
            db.flush()
        has_admin = db.scalar(
            select(RoleBinding).where(
                RoleBinding.user_id == user.id,
                RoleBinding.role == Role.ADMINISTRATOR,
                RoleBinding.domain_slug.is_(None),
            )
        )
        if has_admin is None:
            db.add(RoleBinding(user_id=user.id, role=Role.ADMINISTRATOR))
        db.commit()
        return user


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Uso: python -m app.create_admin <email> <nome> <senha>")
        raise SystemExit(1)
    u = ensure_admin(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"Administrador garantido: {u.email}")
