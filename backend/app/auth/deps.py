import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, selectinload

from app.auth.jwt import decode_access_token
from app.db import get_db
from app.models.auth import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado"
    )
    if creds is None:
        raise unauthorized
    try:
        user_id = decode_access_token(creds.credentials)
    except (pyjwt.PyJWTError, ValueError, KeyError):
        raise unauthorized from None
    user = db.get(User, user_id, options=[selectinload(User.bindings)])
    if user is None or not user.active:
        raise unauthorized
    return user
