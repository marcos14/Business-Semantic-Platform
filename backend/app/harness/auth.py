"""Autenticação dos agentes remotos: credencial `client_id.secret` rotacionável e revogável,
no mesmo padrão das aplicações do help desk. Nunca um JWT de usuário copiado à mão."""

import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.harness import HarnessAgent

AGENT_KEY_HEADER = "X-BSP-Agent-Key"
_agent_key = APIKeyHeader(name=AGENT_KEY_HEADER, auto_error=False)


def credential_hash(secret: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), secret.encode(), hashlib.sha256).hexdigest()


def split_key(api_key: str | None) -> tuple[str, str] | None:
    if not api_key or "." not in api_key:
        return None
    client_id, secret = api_key.split(".", 1)
    return (client_id, secret) if client_id and secret else None


def get_current_agent(
    api_key: str | None = Depends(_agent_key),
    db: Session = Depends(get_db),
) -> HarnessAgent:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Credencial de agente inválida")
    partes = split_key(api_key)
    if partes is None:
        raise unauthorized
    client_id, secret = partes
    agent = db.scalar(select(HarnessAgent).where(HarnessAgent.client_id == client_id))
    if (
        agent is None
        or not agent.active
        or not hmac.compare_digest(agent.secret_hash, credential_hash(secret))
    ):
        raise unauthorized
    agent.last_seen_at = datetime.now(UTC)
    db.commit()
    return agent
