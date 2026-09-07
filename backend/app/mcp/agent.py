"""Assistente interno: tool calling via OpenRouter (modelo do .env) sobre o catálogo de tools.

O mesmo catálogo do servidor MCP, executado em processo. Usado pelo endpoint
``POST /assistant/chat`` (com o JWT do usuário logado) e pela CLI::

    uv run python -m app.mcp.agent "como está o andamento da source X?"
    uv run python -m app.mcp.agent            # REPL
    uv run python -m app.mcp.agent --read-only --groups meta,metrics "..."
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.mcp.client import BspApiError, BspClient
from app.mcp.prompts import assistant_system_prompt
from app.mcp.registry import ToolError, ToolRegistry

log = logging.getLogger(__name__)

TOOL_RESULT_MAX_CHARS = 24_000


@dataclass
class Step:
    tool: str
    arguments: dict
    ok: bool
    result_preview: str

    def as_dict(self) -> dict:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "ok": self.ok,
            "result_preview": self.result_preview,
        }


@dataclass
class AssistantResult:
    reply: str
    steps: list[Step] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)
    truncated: bool = False

    def as_dict(self) -> dict:
        return {
            "reply": self.reply,
            "steps": [s.as_dict() for s in self.steps],
            "model": self.model,
            "usage": self.usage,
            "truncated": self.truncated,
        }


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _compact(value: Any, limit: int = TOOL_RESULT_MAX_CHARS) -> str:
    text = value if isinstance(value, str) else _dumps(value)
    if len(text) <= limit:
        return text
    omitidos = len(text) - limit
    return text[:limit] + f"\n…[truncado: {omitidos} caracteres omitidos; refine os filtros]"


class Assistant:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        max_steps: int = 12,
        read_only: bool = False,
        groups: set[str] | None = None,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ):
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY não configurada no .env")
        self.registry = registry
        self.model = model
        self.max_steps = max_steps
        self.read_only = read_only
        self.groups = groups
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/bsp",
                "X-Title": "BSP Assistant",
            },
        )

    @classmethod
    def from_settings(
        cls, registry: ToolRegistry, *, read_only: bool = False, groups: set[str] | None = None
    ) -> Assistant:
        from app.config import settings

        return cls(
            registry,
            model=settings.assistant_model or settings.openrouter_model,
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            max_steps=settings.assistant_max_steps,
            read_only=read_only,
            groups=groups,
        )

    # ---------- loop ----------

    def tools_payload(self) -> list[dict]:
        specs = self.registry.select(groups=self.groups, read_only=self.read_only)
        return [s.as_openai_tool() for s in specs]

    def _complete(self, messages: list[dict], tools: list[dict] | None) -> dict:
        body: dict = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        r = self._http.post("/chat/completions", json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        if "error" in data and not data.get("choices"):
            raise RuntimeError(f"OpenRouter: {data['error']}")
        return data

    def run(
        self,
        messages: list[dict],
        client: BspClient,
        *,
        user: dict | None = None,
        extra_system: str | None = None,
        on_step: Callable[[Step], None] | None = None,
    ) -> AssistantResult:
        """``messages``: histórico [{role: user|assistant, content}]; o último é a pergunta."""
        system = assistant_system_prompt(user=user, extra=extra_system)
        if self.read_only:
            system += "\n\nMODO SOMENTE LEITURA: nenhuma tool de escrita está disponível."
        convo: list[dict] = [{"role": "system", "content": system}, *messages]
        tools = self.tools_payload()
        result = AssistantResult(reply="", model=self.model)
        usage_total: dict[str, int] = {}

        for _ in range(self.max_steps):
            data = self._complete(convo, tools)
            _accumulate(usage_total, data.get("usage") or {})
            choice = data["choices"][0]
            msg = choice["message"]
            calls = msg.get("tool_calls") or []
            if not calls:
                result.reply = (msg.get("content") or "").strip()
                result.usage = usage_total
                return result
            convo.append(
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": calls,
                }
            )
            for call in calls:
                step = self._execute(call, client)
                result.steps.append(step)
                if on_step:
                    on_step(step)
                convo.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": step.result_preview,
                    }
                )

        # Esgotou o orçamento de passos: pede o fechamento sem novas tools.
        convo.append(
            {
                "role": "user",
                "content": (
                    "Limite de chamadas atingido. Responda agora com o que já apurou, "
                    "dizendo o que ficou por verificar."
                ),
            }
        )
        data = self._complete(convo, None)
        _accumulate(usage_total, data.get("usage") or {})
        result.reply = (data["choices"][0]["message"].get("content") or "").strip()
        result.usage = usage_total
        result.truncated = True
        return result

    def _execute(self, call: dict, client: BspClient) -> Step:
        name = call["function"]["name"]
        raw = call["function"].get("arguments") or "{}"
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError as e:
            return Step(name, {}, False, _dumps({"error": f"argumentos não são JSON: {e}"}))
        allowed = {
            s.name for s in self.registry.select(groups=self.groups, read_only=self.read_only)
        }
        if name not in allowed:
            return Step(
                name, arguments, False,
                _dumps({"error": f"tool '{name}' não disponível nesta sessão"}),
            )
        try:
            value = self.registry.call(name, arguments, client)
            return Step(name, arguments, True, _compact(value))
        except (ToolError, BspApiError) as e:
            log.info("tool %s falhou: %s", name, e)
            return Step(name, arguments, False, _dumps({"error": str(e)}))
        except httpx.HTTPError as e:
            return Step(name, arguments, False, _dumps({"error": f"API inacessível: {e}"}))

    def close(self) -> None:
        self._http.close()


def _utf8_console() -> None:
    """Console do Windows nasce em cp1252: acentos e setas quebrariam o print."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _accumulate(total: dict[str, int], usage: dict) -> None:
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if isinstance(usage.get(k), int):
            total[k] = total.get(k, 0) + usage[k]


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bsp-assistant", description=__doc__)
    parser.add_argument("question", nargs="?", help="pergunta única; sem ela abre um REPL")
    parser.add_argument("--read-only", action="store_true", help="sem tools de escrita")
    parser.add_argument("--groups", default=None, help="grupos de tools, separados por vírgula")
    parser.add_argument(
        "--model", default=None, help="sobrescreve ASSISTANT_MODEL/OPENROUTER_MODEL"
    )
    parser.add_argument("--quiet", action="store_true", help="não mostra as tools chamadas")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    _utf8_console()
    from app.mcp.client import client_from_settings
    from app.mcp.tools import registry

    groups = {g.strip() for g in args.groups.split(",")} if args.groups else None
    assistant = Assistant.from_settings(registry, read_only=args.read_only, groups=groups)
    if args.model:
        assistant.model = args.model
    client = client_from_settings()

    def show(step: Step) -> None:
        if args.quiet:
            return
        marca = "✓" if step.ok else "✗"
        print(f"  {marca} {step.tool}({_dumps(step.arguments)})", file=sys.stderr)

    try:
        me = client.get("/auth/me")
    except BspApiError as e:
        print(f"Falha ao autenticar na API ({client.base_url}): {e.detail}", file=sys.stderr)
        return 1

    history: list[dict] = []

    def ask(text: str) -> None:
        history.append({"role": "user", "content": text})
        res = assistant.run(history, client, user=me, on_step=show)
        history.append({"role": "assistant", "content": res.reply})
        print(res.reply)
        if res.truncated:
            print("(resposta fechada após o limite de chamadas)", file=sys.stderr)

    try:
        if args.question:
            ask(args.question)
            return 0
        print(f"Assistente BSP · {assistant.model} · {me['email']} · 'sair' para encerrar",
              file=sys.stderr)
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line.lower() in {"sair", "exit", "quit"}:
                break
            ask(line)
        return 0
    finally:
        assistant.close()
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
