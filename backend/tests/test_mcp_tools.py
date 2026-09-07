"""Catálogo de tools MCP: schemas, flags de escrita, passthrough e relatórios compostos."""

import pytest
from fake_bsp import FakeClient

from app.mcp.client import BspApiError
from app.mcp.registry import ToolError
from app.mcp.tools import registry

EXPECTED_GROUPS = {
    "meta", "admin", "sources", "discovery", "knowledge", "reviews", "conflicts",
    "questions", "consume", "metrics", "helpdesk", "notifications",
}


def test_catalogo_cobre_as_areas_da_plataforma():
    assert set(registry.groups()) == EXPECTED_GROUPS
    assert len(registry.tools) >= 60
    for spec in registry.tools.values():
        assert spec.description, spec.name
        schema = spec.input_schema()
        assert schema["type"] == "object", spec.name
        assert "title" not in schema, spec.name
        tool = spec.as_openai_tool()
        assert tool["function"]["name"] == spec.name


def test_flags_de_escrita_e_selecao_somente_leitura():
    assert not registry.tools["list_sources"].mutating
    assert registry.tools["create_user"].mutating
    assert registry.tools["decide"].destructive and registry.tools["decide"].mutating
    assert registry.tools["revoke_role"].destructive
    leitura = registry.select(read_only=True)
    assert leitura and all(not s.mutating for s in leitura)
    so_meta = registry.select(groups={"meta"})
    assert {s.group for s in so_meta} == {"meta"}
    assert {s.name for s in so_meta} == {"whoami", "platform_overview", "source_progress"}


def test_schema_reflete_tipos_e_obrigatorios():
    schema = registry.tools["list_atoms"].input_schema()
    statuses = schema["properties"]["statuses"]
    enum = statuses["anyOf"][0]["items"]["enum"]
    assert "CANONICAL" in enum and "PROVISIONAL" in enum
    assert "required" not in schema  # tudo opcional

    cand = registry.tools["create_candidate"].input_schema()
    assert set(cand["required"]) == {"kind", "title", "domain"}
    assert cand["properties"]["scope"]["description"].startswith("ex.:")

    vote = registry.tools["vote"].input_schema()
    assert "CONFIRM" in vote["properties"]["action"]["enum"]


def test_argumentos_invalidos_viram_tool_error_legivel():
    fc = FakeClient()
    with pytest.raises(ToolError, match="atom_id"):
        registry.call("get_atom", {}, fc)
    with pytest.raises(ToolError, match="action"):
        registry.call("vote", {"atom_id": "x", "action": "NOPE"}, fc)
    with pytest.raises(ToolError, match="desconhecida"):
        registry.call("nao_existe", {}, fc)
    assert fc.calls == []


def test_passthrough_monta_query_e_body():
    fc = FakeClient({"/knowledge": {"total": 0, "items": []}})
    registry.call(
        "list_atoms", {"domain": "finance", "statuses": ["CANONICAL", "PROVISIONAL"], "limit": 5},
        fc,
    )
    method, path, params, _ = fc.calls[0]
    assert (method, path) == ("GET", "/knowledge")
    assert params["statuses"] == "CANONICAL,PROVISIONAL"
    assert params["domain"] == "finance" and params["limit"] == 5

    registry.call(
        "create_candidate",
        {"kind": "rule", "title": "Prazo", "domain": "finance", "statement": "Cancela em 7 dias"},
        fc,
    )
    _, path, _, body = fc.calls[1]
    assert path == "/knowledge/candidates"
    assert body["body"] == {"statement": "Cancela em 7 dias"}
    assert body["description"] == "Cancela em 7 dias"
    assert body["evidence"] == []

    registry.call("update_user", {"user_id": "u1", "name": "Novo"}, fc)
    _, path, _, body = fc.calls[2]
    assert path == "/admin/users/u1" and body == {"name": "Novo"}

    registry.call("get_atom", {"atom_id": "a1", "include": ["evidence", "graph"]}, fc)
    assert fc.paths()[3:] == ["/knowledge/a1", "/knowledge/a1/evidence", "/graph"]
    assert fc.calls[-1][2] == {"atom_id": "a1", "depth": 1}

    registry.call("projection", {"kind": "bdd", "atom_id": "s1"}, fc)
    assert fc.paths()[-1] == "/projections/bdd/s1"
    registry.call("metrics", {"report": "coverage_by_capability", "domain": "finance"}, fc)
    assert fc.paths()[-1] == "/metrics/coverage-by-capability"


def test_platform_overview_interpreta_alertas_e_tolera_403():
    fc = FakeClient(
        {
            "/auth/me": {"email": "ana@x", "name": "Ana", "bindings": []},
            "/sources": [
                {"id": "s1", "name": "ERP", "type": "source_code", "domain_slug": "finance",
                 "repository": "C:/erp"}
            ],
            "/discovery/batches": [
                {"batch_id": "b1", "agent": "code", "domain": "finance", "capability": "billing",
                 "source_id": "s1", "active": True, "done": 3, "total": 10, "failed": 1,
                 "blocked": 0, "candidates": 12, "cost_usd": 4.2}
            ],
            "/discovery/queue": {"pending": 7, "running": 0, "workers_alive": 0,
                                 "scheduled_future": 2, "next_scheduled_at": "2026-09-07T20:00"},
            "/reviews/inbox": {
                "summary": {"awaiting_review": 4, "needs_decision": 2, "with_conflicts": 0,
                            "canonical_challenged": 1, "provisional": 9, "awaiting_evidence": 3},
                "items": [{"id": "a1", "title": "Regra", "status": "DECISION_PENDING",
                           "risk": "HIGH", "confidence": 0.7, "priority": {"score": 0.9}}],
            },
            "/metrics/coverage": {"total_atoms": 40},
            "/metrics/attention": BspApiError(
                403, "Permissão insuficiente", "GET", "/metrics/attention"
            ),
            "/conflicts": [{"id": "c1"}],
            "/questions": [],
            "/metrics/recent-events": [],
        }
    )
    out = registry.call("platform_overview", {}, fc)
    assert out["user"]["email"] == "ana@x"
    assert out["sources"]["total"] == 1
    assert out["discovery"]["active_batches"][0]["batch_id"] == "b1"
    assert out["discovery"]["queue"]["workers_alive"] == 0
    assert out["attention"] == {"error": "HTTP 403: Permissão insuficiente"}
    assert out["inbox_top"][0]["id"] == "a1"
    alertas = "\n".join(out["alerts"])
    assert "NENHUM worker" in alertas
    assert "1 run(s) de discovery falharam" in alertas
    assert "2 job(s) reagendados" in alertas
    assert "2 atom(s) aguardam SUA decisão" in alertas
    assert "1 conflito(s) abertos" in alertas
    assert "canônico(s) desafiados" in alertas


def test_platform_overview_alerta_pendentes_sem_execucao():
    fc = FakeClient(
        {
            "/auth/me": {"email": "a@x", "bindings": []},
            "/discovery/queue": {"pending": 6, "running": 0, "workers_alive": 1,
                                 "scheduled_future": 0},
            "/reviews/inbox": {"summary": {}, "items": []},
        }
    )
    out = registry.call("platform_overview", {}, fc)
    assert any("sem nenhum em execu" in a for a in out["alerts"])
    assert not any("NENHUM worker" in a for a in out["alerts"])


def test_source_progress_recomenda_proximos_passos():
    fc = FakeClient(
        {
            "/sources/s1": {"id": "s1", "name": "ERP", "repository": "C:/erp",
                            "domain_slug": "finance"},
            "/sources/s1/inventory/summary": {
                "files": 10, "files_with_capability": 8, "files_without_capability": 2,
                "capabilities": [
                    {"slug": "billing", "files": 5, "by_relevance": {"1": 1, "2": 2, "3": 2}},
                    {"slug": "cancel", "files": 3, "by_relevance": {"1": 3, "2": 0, "3": 0}},
                ],
                "suggestions": [{"name": "Comissões"}],
            },
            "/discovery/batches": [
                {"batch_id": "b0", "agent": "inventory", "source_id": "s1", "active": False,
                 "capability": None, "blocked": 0}
            ],
            "/discovery/runs": [
                {"id": "r1", "source_id": "s1", "status": "failed", "agent": "inventory",
                 "error": "boom", "cost_usd": 1.5, "candidates_created": 0,
                 "started_at": "2026-09-07T10:00"},
                {"id": "r2", "source_id": "OUTRA", "status": "succeeded", "agent": "code",
                 "cost_usd": 9, "candidates_created": 5, "started_at": "2026-09-07T11:00"},
            ],
            "/metrics/coverage-by-capability": [{"capability": "billing", "candidates": 4}],
        }
    )
    out = registry.call("source_progress", {"source_id": "s1"}, fc)
    assert out["runs"]["total"] == 1 and out["runs"]["cost_usd"] == 1.5
    assert out["runs"]["errors_sample"] == ["boom"]
    passos = "\n".join(out["next_steps"])
    assert "Comissões" in passos and "create_capability" in passos
    assert "billing (4 arquivos relevantes)" in passos
    assert "cancel" not in passos  # só relevância 1: não vale campanha
    assert "1 run(s) falharam" in passos
    assert "4 candidate(s) do domain aguardam" in passos


def test_source_progress_sem_repositorio_orienta_cadastro():
    fc = FakeClient({"/sources/s2": {"id": "s2", "name": "Docs", "repository": None,
                                     "domain_slug": None}})
    out = registry.call("source_progress", {"source_id": "s2"}, fc)
    passos = "\n".join(out["next_steps"])
    assert "repository" in passos and "domain_slug" in passos
