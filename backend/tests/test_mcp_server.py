"""Servidor MCP ponta a ponta (cliente e servidor ligados por streams em memória)."""

import anyio
from fake_bsp import FakeClient
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from app.mcp.server import build_server
from app.mcp.tools import registry


def _roundtrip(server, calls):
    """Sobe o servidor, inicializa a sessão, executa ``calls(session)`` e devolve o resultado."""

    async def scenario():
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    server.run,
                    server_streams[0],
                    server_streams[1],
                    server.create_initialization_options(),
                )
                async with ClientSession(client_streams[0], client_streams[1]) as session:
                    await session.initialize()
                    out = await calls(session)
                tg.cancel_scope.cancel()
            return out

    return anyio.run(scenario)


def test_lista_tools_com_anotacoes_e_executa_chamadas():
    fake = FakeClient({"/auth/me": {"email": "ana@x", "bindings": []}})
    created = []

    def factory():
        created.append(1)
        return fake

    server = build_server(registry, factory)

    async def calls(session):
        tools = await session.list_tools()
        ok = await session.call_tool("whoami", {})
        bad_args = await session.call_tool("get_atom", {})
        unknown = await session.call_tool("nao_existe", {})
        return tools, ok, bad_args, unknown

    tools, ok, bad_args, unknown = _roundtrip(server, calls)

    by_name = {t.name: t for t in tools.tools}
    assert "platform_overview" in by_name and len(by_name) == len(registry.tools)
    assert by_name["list_sources"].annotations.read_only_hint is True
    assert by_name["create_user"].annotations.read_only_hint is False
    assert by_name["decide"].annotations.destructive_hint is True
    assert by_name["get_atom"].input_schema["required"] == ["atom_id"]

    assert not ok.is_error
    assert ok.structured_content["email"] == "ana@x"
    assert "ana@x" in ok.content[0].text
    assert bad_args.is_error and "atom_id" in bad_args.content[0].text
    assert unknown.is_error and "desconhecida" in unknown.content[0].text
    assert created == [1]  # cliente criado uma vez, sob demanda


def test_servidor_somente_leitura_nao_expoe_escrita():
    server = build_server(registry, FakeClient, read_only=True, groups={"admin", "meta"})

    async def calls(session):
        tools = await session.list_tools()
        blocked = await session.call_tool("create_user", {
            "email": "x@y", "name": "X", "password": "12345678"})
        return tools, blocked

    tools, blocked = _roundtrip(server, calls)
    names = {t.name for t in tools.tools}
    assert "list_users" in names and "whoami" in names
    assert "create_user" not in names and "list_sources" not in names
    assert blocked.is_error
