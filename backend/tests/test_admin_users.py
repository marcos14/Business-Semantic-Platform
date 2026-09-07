"""Endpoints adicionados para o assistente/MCP: PATCH de usuário, listagem de bindings e
/assistant/* (exigem Postgres; ver conftest)."""

import pytest

from app.mcp.agent import AssistantResult


def _login(client, email: str, password: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin(client):
    from app.create_admin import ensure_admin

    ensure_admin("mcp-admin@example.com", "MCP Admin", "admin-s3nha")
    return _login(client, "mcp-admin@example.com", "admin-s3nha")


def test_patch_usuario_nome_senha_e_situacao(client, admin):
    r = client.post(
        "/admin/users",
        json={"email": "dora@example.com", "name": "Dora", "password": "dora-s3nha"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]

    r = client.patch(f"/admin/users/{uid}", json={"name": "Dora Silva"}, headers=admin)
    assert r.status_code == 200 and r.json()["name"] == "Dora Silva"

    r = client.patch(f"/admin/users/{uid}", json={"password": "nova-s3nha-1"}, headers=admin)
    assert r.status_code == 200
    _login(client, "dora@example.com", "nova-s3nha-1")

    r = client.patch(f"/admin/users/{uid}", json={"active": False}, headers=admin)
    assert r.status_code == 200 and r.json()["active"] is False
    assert (
        client.post(
            "/auth/login", json={"email": "dora@example.com", "password": "nova-s3nha-1"}
        ).status_code
        == 401
    )

    r = client.patch(f"/admin/users/{uid}", json={"password": "curta"}, headers=admin)
    assert r.status_code == 422
    import uuid

    r = client.patch(f"/admin/users/{uuid.uuid4()}", json={"name": "x"}, headers=admin)
    assert r.status_code == 404


def test_admin_nao_desativa_a_si_mesmo(client, admin):
    me = client.get("/auth/me", headers=admin).json()
    r = client.patch(f"/admin/users/{me['id']}", json={"active": False}, headers=admin)
    assert r.status_code == 422


def test_lista_bindings_por_usuario(client, admin):
    client.post("/admin/domains", json={"slug": "mcp-dom", "name": "MCP"}, headers=admin)
    r = client.post(
        "/admin/users",
        json={"email": "eli@example.com", "name": "Eli", "password": "eli-s3nha!"},
        headers=admin,
    )
    uid = r.json()["id"]
    r = client.post(
        "/admin/role-bindings",
        json={"user_id": uid, "role": "reviewer", "domain_slug": "mcp-dom"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    bid = r.json()["id"]

    todos = client.get("/admin/role-bindings", headers=admin).json()
    assert any(b["id"] == bid for b in todos)
    do_eli = client.get(f"/admin/role-bindings?user_id={uid}", headers=admin).json()
    assert [b["id"] for b in do_eli] == [bid]
    assert do_eli[0]["role"] == "reviewer" and do_eli[0]["domain_slug"] == "mcp-dom"

    eli = _login(client, "eli@example.com", "eli-s3nha!")
    assert client.get("/admin/role-bindings", headers=eli).status_code == 403


def test_assistant_tools_e_chat(client, admin, monkeypatch):
    r = client.get("/assistant/tools", headers=admin)
    assert r.status_code == 200
    nomes = {t["name"] for t in r.json()}
    assert {"platform_overview", "source_progress", "update_user"} <= nomes
    assert client.get("/assistant/tools").status_code == 401

    from app.assistant import router as mod
    from app.config import settings

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = client.post(
        "/assistant/chat", json={"messages": [{"role": "user", "content": "oi"}]}, headers=admin
    )
    assert r.status_code == 400 and "OPENROUTER_API_KEY" in r.json()["detail"]

    class Stub:
        def __init__(self):
            self.seen = None

        def run(self, messages, client_, *, user=None, extra_system=None):
            self.seen = (messages, user, extra_system, client_)
            return AssistantResult(reply=f"eco: {messages[-1]['content']}", model="stub")

        def close(self):
            pass

    stub = Stub()
    monkeypatch.setattr(mod.Assistant, "from_settings", classmethod(lambda cls, *a, **k: stub))
    r = client.post(
        "/assistant/chat",
        json={"messages": [{"role": "user", "content": "andamento?"}], "domain": "mcp-dom"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "eco: andamento?" and r.json()["steps"] == []
    messages, user, extra, bsp_client = stub.seen
    assert user["email"] == "mcp-admin@example.com"
    assert user["bindings"][0]["role"] == "administrator"
    assert "mcp-dom" in extra
    assert bsp_client.authenticated  # JWT de quem perguntou foi repassado

    r = client.post(
        "/assistant/chat",
        json={"messages": [{"role": "assistant", "content": "x"}]},
        headers=admin,
    )
    assert r.status_code == 400
