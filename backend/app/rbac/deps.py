from fastapi import Depends, HTTPException, status

from app.auth.deps import get_current_user
from app.models.auth import Role, User
from app.rbac.roles import has_role


def require(role: Role):
    """Dependency factory: exige um papel em escopo global."""

    def dep(user: User = Depends(get_current_user)) -> User:
        if not has_role(user, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Permissão insuficiente"
            )
        return user

    return dep
