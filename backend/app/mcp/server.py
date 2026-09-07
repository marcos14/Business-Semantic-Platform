"""Servidor MCP da plataforma (SDK ``mcp`` 2.x, servidor de baixo nível).

Transportes:

- ``stdio`` (padrão) — para Claude Code e outros clientes locais. Nunca escreva em stdout
  aqui fora do protocolo: logs vão para stderr.
- ``http`` — Streamable HTTP em ``/mcp`` para consumo remoto (``--host``/``--port``).

Credenciais e URL da API vêm do ``.env`` (BSP_API_URL, BSP_TOKEN ou BSP_EMAIL/BSP_PASSWORD).
Exemplo (Claude Code, na raiz do repositório)::

    claude mcp add bsp -- uv run --directory backend python -m app.mcp.server

ou use o ``.mcp.json`` já presente na raiz.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from typing import Any

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from app.mcp.client import BspApiError, BspClient
from app.mcp.prompts import SERVER_INSTRUCTIONS
from app.mcp.registry import ToolError, ToolRegistry

log = logging.getLogger(__name__)

SERVER_NAME = "bsp"
SERVER_VERSION = "0.1.0"


def build_server(
    registry: ToolRegistry,
    client_factory: Callable[[], BspClient],
    *,
    groups: set[str] | None = None,
    read_only: bool = False,
) -> Server:
    specs = {s.name: s for s in registry.select(groups=groups, read_only=read_only)}
    state: dict[str, BspClient] = {}

    def client() -> BspClient:
        if "client" not in state:
            state["client"] = client_factory()
        return state["client"]

    async def on_list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=s.name,
                    description=s.description,
                    input_schema=s.input_schema(),
                    annotations=types.ToolAnnotations(
                        title=s.name.replace("_", " "),
                        read_only_hint=not s.mutating,
                        destructive_hint=s.destructive,
                        idempotent_hint=s.idempotent or not s.mutating,
                        open_world_hint=False,
                    ),
                    meta={"group": s.group},
                )
                for s in specs.values()
            ]
        )

    async def on_call_tool(_ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name not in specs:
            return _error(f"Tool desconhecida ou indisponível nesta sessão: {params.name}")
        try:
            value = await anyio.to_thread.run_sync(
                lambda: registry.call(params.name, params.arguments or {}, client())
            )
        except (ToolError, BspApiError) as e:
            return _error(str(e))
        except Exception as e:  # rede, JSON malformado etc.: erro legível, não crash
            log.exception("tool %s falhou", params.name)
            return _error(f"Falha ao executar {params.name}: {e}")
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, default=str)
        structured = value if isinstance(value, dict) else {"result": value}
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            structured_content=structured,
        )

    return Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        title="Business Semantic Platform",
        instructions=SERVER_INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], is_error=True
    )


async def run_stdio(server: Server) -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bsp-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--groups", default=None, help="grupos de tools, separados por vírgula")
    parser.add_argument("--read-only", action="store_true", help="expõe só tools de leitura")
    parser.add_argument("--list", action="store_true", help="lista as tools e sai")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    from app.mcp.client import client_from_settings
    from app.mcp.tools import registry

    groups = {g.strip() for g in args.groups.split(",")} if args.groups else None
    if args.list:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        for s in registry.select(groups=groups, read_only=args.read_only):
            flag = "rw" if s.mutating else "ro"
            print(f"{s.name:32} {flag}  [{s.group}]  {s.description.splitlines()[0]}")
        return 0

    server = build_server(registry, client_from_settings, groups=groups, read_only=args.read_only)
    if args.transport == "stdio":
        anyio.run(run_stdio, server)
        return 0

    import uvicorn

    app = server.streamable_http_app(host=args.host)
    log.info("MCP streamable HTTP em http://%s:%s/mcp", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
