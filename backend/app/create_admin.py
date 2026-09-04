"""Bootstrap do primeiro administrador.

Uso: python -m app.create_admin <email> <nome> <senha> [--reset-password]
Idempotente: se o usuário existir, garante o binding de administrator global.
Com --reset-password, também redefine a senha do usuário existente (recuperação de acesso).
"""

import sys

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.models.auth import Role, RoleBinding, User


def ensure_admin(email: str, name: str, password: str, *, reset_password: bool = False) -> User:
    email = email.lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=name, password_hash=hash_password(password))
            db.add(user)
            db.flush()
        elif reset_password:
            user.password_hash = hash_password(password)
            user.active = True
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
    args = [a for a in sys.argv[1:] if a != "--reset-password"]
    reset = "--reset-password" in sys.argv
    if len(args) != 3:
        print("Uso: python -m app.create_admin <email> <nome> <senha> [--reset-password]")
        raise SystemExit(1)
    u = ensure_admin(args[0], args[1], args[2], reset_password=reset)
    print(f"Administrador garantido: {u.email}" + (" (senha redefinida)" if reset else ""))
