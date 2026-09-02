import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import settings

ALGORITHM = "HS256"


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Devolve o user_id do token. Levanta jwt.PyJWTError/ValueError se inválido ou expirado."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    return uuid.UUID(payload["sub"])
