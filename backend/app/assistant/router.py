"""Assistente operacional na API: o agente OpenRouter roda em processo, com as tools MCP
apontadas para esta mesma API e autenticadas com o JWT de quem perguntou — logo, com
exatamente as permissões dele."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth.deps import get_current_user
from app.config import settings
from app.kernel.errors import KernelError
from app.mcp.agent import Assistant
from app.mcp.client import BspClient
from app.mcp.tools import registry
from app.models.auth import User

router = APIRouter(prefix="/assistant", tags=["assistant"])


class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatIn(BaseModel):
    messages: list[MessageIn] = Field(min_length=1, max_length=60)
    read_only: bool = False
    domain: str | None = Field(default=None, description="dica de escopo para o assistente")


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _user_dict(user: User) -> dict:
    return {
        "email": user.email,
        "name": user.name,
        "bindings": [
            {"role": b.role.value, "domain": b.domain_slug, "capability": b.capability_slug}
            for b in user.bindings
        ],
    }


@router.get("/tools")
def list_tools(_user: User = Depends(get_current_user)) -> list[dict]:
    """Catálogo das tools que o assistente (e o servidor MCP) expõe."""
    return [
        {
            "name": s.name,
            "group": s.group,
            "description": s.description,
            "mutating": s.mutating,
            "destructive": s.destructive,
        }
        for s in registry.tools.values()
    ]


@router.post("/chat")
def chat(
    body: ChatIn, request: Request, user: User = Depends(get_current_user)
) -> dict:
    if body.messages[-1].role != "user":
        raise KernelError("A última mensagem precisa ser do usuário")
    try:
        assistant = Assistant.from_settings(registry, read_only=body.read_only)
    except RuntimeError as e:
        raise KernelError(f"Assistente indisponível: {e}") from None
    client = BspClient(settings.bsp_api_url, token=_bearer(request))
    extra = f"Escopo sugerido pelo usuário: domain `{body.domain}`." if body.domain else None
    try:
        result = assistant.run(
            [m.model_dump() for m in body.messages],
            client,
            user=_user_dict(user),
            extra_system=extra,
        )
    except RuntimeError as e:
        raise KernelError(f"Assistente indisponível: {e}") from None
    finally:
        assistant.close()
        client.close()
    return result.as_dict()
