"""Loop de tool calling do assistente com a OpenRouter simulada (httpx.MockTransport)."""

import json

import httpx
import pytest
from fake_bsp import FakeClient

from app.mcp.agent import Assistant
from app.mcp.tools import registry


def _assistant_message(content=None, tool_calls=None) -> dict:
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
            for i, (name, args) in enumerate(tool_calls)
        ]
    return {"choices": [{"message": msg}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def _make(script, **kw) -> tuple[Assistant, list[dict]]:
    """``script``: função(body_da_requisição, nº_da_chamada) -> resposta JSON."""
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=script(body, len(requests)))

    a = Assistant(
        registry, model="test/model", api_key="k", transport=httpx.MockTransport(handler), **kw
    )
    return a, requests


def test_executa_tool_e_devolve_resposta_final():
    def script(body, n):
        if n == 1:
            return _assistant_message(tool_calls=[("list_sources", {"domain": "finance"})])
        return _assistant_message(content="Há 1 source: ERP.")

    a, requests = _make(script)
    fc = FakeClient({"/sources": [{"id": "s1", "name": "ERP", "domain_slug": "finance"}]})
    res = a.run([{"role": "user", "content": "quais sources?"}], fc, user={"email": "ana@x"})

    assert res.reply == "Há 1 source: ERP."
    assert [s.tool for s in res.steps] == ["list_sources"]
    assert res.steps[0].ok and "ERP" in res.steps[0].result_preview
    assert res.usage["prompt_tokens"] == 20 and not res.truncated
    # 1ª requisição leva o catálogo de tools e o system prompt com o usuário
    assert requests[0]["tool_choice"] == "auto"
    nomes = {t["function"]["name"] for t in requests[0]["tools"]}
    assert "platform_overview" in nomes and "create_user" in nomes
    assert requests[0]["messages"][0]["role"] == "system"
    assert "ana@x" in requests[0]["messages"][0]["content"]
    # 2ª requisição leva o resultado da tool no formato OpenAI
    papeis = [m["role"] for m in requests[1]["messages"]]
    assert papeis[-2:] == ["assistant", "tool"]
    assert requests[1]["messages"][-1]["tool_call_id"] == "call_0"


def test_modo_somente_leitura_oculta_e_bloqueia_escrita():
    def script(body, n):
        if n == 1:
            return _assistant_message(tool_calls=[("create_user", {
                "email": "x@y", "name": "X", "password": "12345678"})])
        return _assistant_message(content="não posso criar")

    a, requests = _make(script, read_only=True)
    fc = FakeClient()
    res = a.run([{"role": "user", "content": "crie usuário"}], fc)
    nomes = {t["function"]["name"] for t in requests[0]["tools"]}
    assert "create_user" not in nomes and "list_users" in nomes
    assert not res.steps[0].ok and "não disponível" in res.steps[0].result_preview
    assert fc.calls == []  # nada chegou à API
    assert "SOMENTE LEITURA" in requests[0]["messages"][0]["content"]


def test_erro_da_api_vira_resultado_de_tool_sem_derrubar_o_loop():
    from app.mcp.client import BspApiError

    def script(body, n):
        if n == 1:
            return _assistant_message(tool_calls=[("list_users", {})])
        return _assistant_message(content="sem permissão para listar usuários")

    a, _ = _make(script)
    fc = FakeClient({"/admin/users": BspApiError(403, "Permissão insuficiente", "GET",
                                                 "/admin/users")})
    res = a.run([{"role": "user", "content": "usuários?"}], fc)
    assert not res.steps[0].ok and "HTTP 403" in res.steps[0].result_preview
    assert res.reply.startswith("sem permissão")


def test_argumentos_invalidos_e_json_quebrado_sao_reportados():
    def script(body, n):
        if n == 1:
            return {
                "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "get_atom", "arguments": "{nao é json"}},
                    {"id": "c2", "type": "function",
                     "function": {"name": "vote", "arguments": json.dumps({"atom_id": "a"})}},
                ]}}],
            }
        return _assistant_message(content="ok")

    a, _ = _make(script)
    res = a.run([{"role": "user", "content": "x"}], FakeClient())
    assert [s.ok for s in res.steps] == [False, False]
    assert "JSON" in res.steps[0].result_preview
    assert "action" in res.steps[1].result_preview


def test_limite_de_passos_fecha_a_resposta():
    def script(body, n):
        if "tools" in body:
            return _assistant_message(tool_calls=[("whoami", {})])
        assert body["messages"][-1]["role"] == "user"  # pedido de fechamento
        return _assistant_message(content="parcial")

    a, requests = _make(script, max_steps=2)
    res = a.run([{"role": "user", "content": "loop"}], FakeClient({"/auth/me": {"email": "e"}}))
    assert res.truncated and res.reply == "parcial"
    assert len(res.steps) == 2 and len(requests) == 3


def test_erro_http_da_openrouter_vira_runtime_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": {"message": "sem créditos"}})

    a = Assistant(registry, model="m", api_key="k", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="402"):
        a.run([{"role": "user", "content": "oi"}], FakeClient())


def test_sem_chave_falha_cedo():
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        Assistant(registry, model="m", api_key="")
