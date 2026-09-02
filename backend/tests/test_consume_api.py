"""Consumo (§52-§55, §61-§68): explorer, busca, graph/impact, context (AC-CTX), projeções."""

import time

import pytest


def _login(client, email, password="s3nha-teste"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def ctx(client):
    """Domain 'con' com um mini-modelo completo: concept, rules, states, transitions,
    scenario, decision, process, question aberta e conflito aberto."""
    from app.create_admin import ensure_admin
    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, LifecycleStatus, Origin, RelationType
    from app.services.knowledge import add_relation, change_status, create_candidate, get_atom

    ensure_admin("admin@example.com", "Admin", "admin-s3nha")
    admin = _login(client, "admin@example.com", "admin-s3nha")
    client.post("/admin/domains", json={"slug": "con", "name": "Consumo"}, headers=admin)
    client.post(
        "/admin/capabilities",
        json={"slug": "faturamento", "domain_slug": "con", "name": "Faturamento"},
        headers=admin,
    )

    ev = [{"type": "SOURCE_CODE", "location": {"file": "fat.go"}}]

    def _atom(db, kind, title, body=None, atom_id=None, canonical=False, **kw):
        a = create_candidate(
            db, actor="agent:test", origin=Origin.AGENT, kind=kind, title=title,
            domain="con", capability="faturamento", scope={"s": 1},
            body=body, atom_id=atom_id, evidence=ev if kind != AtomKind.QUESTION else [],
            **kw,
        )
        db.flush()
        if canonical:
            for novo in [
                LifecycleStatus.READY_FOR_EVALUATION,
                LifecycleStatus.NEEDS_HUMAN_REVIEW,
                LifecycleStatus.IN_REVIEW,
                LifecycleStatus.DECISION_PENDING,
            ]:
                atom = get_atom(db, a.id)
                change_status(db, a.id, actor="owner@x", new_status=novo, reason="t",
                              expected_lock_version=atom.lock_version)
            atom = get_atom(db, a.id)
            change_status(db, a.id, actor="owner@x", new_status=LifecycleStatus.CANONICAL,
                          reason="t", expected_lock_version=atom.lock_version,
                          authority_granted=True)
        return a.id

    with SessionLocal() as db:
        ids = {}
        ids["concept"] = _atom(db, AtomKind.CONCEPT, "Fatura", canonical=True)
        ids["rule"] = _atom(
            db, AtomKind.RULE, "Fatura vencida bloqueia novos pedidos",
            body={"statement": "Cliente com fatura vencida não pode criar novos pedidos."},
            canonical=True,
        )
        ids["rule_cand"] = _atom(
            db, AtomKind.RULE, "Fatura paga libera limite imediatamente",
            body={"statement": "O pagamento da fatura restaura o limite de crédito."},
        )
        ids["invariant"] = _atom(
            db, AtomKind.INVARIANT, "Saldo da fatura nunca negativo",
            body={"statement": "O saldo remanescente nunca fica negativo."}, canonical=True,
        )
        ids["s_aberta"] = _atom(db, AtomKind.STATE, "Aberta",
                                atom_id="CON.FATURAMENTO.STATE.ABERTA", canonical=True)
        ids["s_paga"] = _atom(db, AtomKind.STATE, "Paga",
                              atom_id="CON.FATURAMENTO.STATE.PAGA", canonical=True)
        ids["transition"] = _atom(
            db, AtomKind.TRANSITION, "Pagamento da fatura",
            body={"from_state": "CON.FATURAMENTO.STATE.ABERTA",
                  "to_state": "CON.FATURAMENTO.STATE.PAGA",
                  "trigger": "pagar_fatura", "conditions": [ids["rule"]]},
            canonical=True,
        )
        ids["scenario"] = _atom(
            db, AtomKind.SCENARIO, "Bloqueio de pedido com fatura vencida",
            body={"given": {"description": "uma fatura vencida do cliente"},
                  "when": {"description": "o cliente tenta criar um pedido"},
                  "then": {"description": "o pedido é rejeitado"}},
            canonical=True,
        )
        ids["decision"] = _atom(
            db, AtomKind.DECISION, "Aprovação de pedido acima do limite",
            body={"inputs": ["customer.risk", "order.amount"], "output": "approval_level",
                  "logic": {"type": "decision_table", "rows": [
                      {"customer.risk": "LOW", "order.amount": "<50k", "output": "auto"},
                      {"customer.risk": "HIGH", "order.amount": "any", "output": "director"},
                  ]}},
            canonical=True,
        )
        ids["process"] = _atom(
            db, AtomKind.PROCESS, "Cobrança de fatura vencida",
            body={"steps": [{"id": "s1", "type": "step", "title": "notificar"}]},
        )
        ids["question"] = _atom(db, AtomKind.QUESTION, "Juros valem em feriados?",
                                body={"question": "Juros valem em feriados?"})
        # graph: processo depende da regra; cenário exemplifica a regra; pedido afeta decisão
        add_relation(db, actor="t", from_atom=ids["process"], to_atom=ids["rule"],
                     relation_type=RelationType.DEPENDS_ON)
        add_relation(db, actor="t", from_atom=ids["rule"], to_atom=ids["scenario"],
                     relation_type=RelationType.EXEMPLIFIED_BY)
        add_relation(db, actor="t", from_atom=ids["rule_cand"], to_atom=ids["process"],
                     relation_type=RelationType.DEPENDS_ON)
        db.commit()

    # conflito aberto: evidência contraditória no candidate
    r = client.post(
        f"/knowledge/{ids['rule_cand']}/evidence",
        json={"type": "TEST", "relation": "contradicts", "summary": "teste diverge"},
        headers=admin,
    )
    assert r.status_code == 201
    return {"admin": admin, "ids": ids}


def test_explorer_arvore_e_capability(client, ctx):
    arvore = client.get("/explorer", headers=ctx["admin"]).json()
    dom = next(d for d in arvore if d["slug"] == "con")
    cap = next(c for c in dom["capabilities"] if c["slug"] == "faturamento")
    assert cap["total"] >= 10 and cap["canonical"] >= 7
    assert cap["by_kind"]["rule"] >= 2

    detalhe = client.get("/explorer/con/faturamento", headers=ctx["admin"]).json()
    assert {"concept", "rule", "state", "transition", "scenario", "decision"} <= set(
        detalhe["kinds"]
    )


def test_busca_fulltext_filtros_e_fuzzy(client, ctx):
    # full-text por palavra do statement
    r = client.get(
        "/search", params={"q": "fatura vencida", "domain": "con"}, headers=ctx["admin"]
    ).json()
    assert any(i["id"] == ctx["ids"]["rule"] for i in r["items"])
    # filtro por status canonical
    r = client.get(
        "/search",
        params={"q": "fatura", "domain": "con", "status": "CANONICAL"},
        headers=ctx["admin"],
    ).json()
    assert all(i["status"] == "CANONICAL" for i in r["items"])
    # fuzzy: erro de digitação ainda encontra pelo título
    r = client.get(
        "/search", params={"q": "faturra vencida bloqueia", "domain": "con"},
        headers=ctx["admin"],
    ).json()
    assert any(i["id"] == ctx["ids"]["rule"] for i in r["items"]), r


def test_graph_e_impact(client, ctx):
    ids = ctx["ids"]
    g = client.get(
        "/graph", params={"atom_id": ids["rule"], "depth": 2}, headers=ctx["admin"]
    ).json()
    nos = {n["id"] for n in g["nodes"]}
    assert {ids["rule"], ids["process"], ids["scenario"]} <= nos

    # §55: mudar a rule afeta o processo (direto), o cenário (direto) e
    # transitivamente a rule_cand (que depende do processo)? não — direção:
    # rule_cand DEPENDS_ON process → mudar process afeta rule_cand → transitivo da rule.
    imp = client.get(f"/knowledge/{ids['rule']}/impact", headers=ctx["admin"]).json()
    diretos = {i["id"] for i in imp["direct"]}
    transitivos = {i["id"] for i in imp["transitive"]}
    assert {ids["process"], ids["scenario"]} <= diretos
    assert ids["rule_cand"] in transitivos
    assert imp["by_kind"]["process"] == 1


def test_centralidade_alimenta_prioridade(client, ctx):
    from app.db import SessionLocal
    from app.models.knowledge import KnowledgeAtom
    from app.services.graph import compute_centrality

    with SessionLocal() as db:
        n = compute_centrality(db)
        db.commit()
        assert n > 0
        rule = db.get(KnowledgeAtom, ctx["ids"]["rule"])
        assert rule.centrality is not None and 0 <= rule.centrality <= 1


def test_ac_ctx_context_package(client, ctx):
    ids = ctx["ids"]
    inicio = time.monotonic()
    pkg = client.get(
        "/context", params={"capability": "faturamento"}, headers=ctx["admin"]
    ).json()
    duracao = time.monotonic() - inicio
    assert duracao < 10  # §122

    # AC-CTX-01: pacote gerado com as seções do §62
    assert pkg["capability"]["slug"] == "faturamento"
    assert {"concepts", "rules", "decisions", "invariants", "states", "transitions",
            "scenarios", "known_conflicts", "open_questions"} <= set(pkg)
    # AC-CTX-02: apenas canonical por padrão
    assert all(i["label"] == "CANONICAL" for i in pkg["rules"])
    assert not any(i["id"] == ids["rule_cand"] for i in pkg["rules"])
    # AC-CTX-03: conflitos e questions claramente identificados (§63)
    assert any(q["label"] == "UNKNOWN" for q in pkg["open_questions"])
    assert any(c["label"] == "UNRESOLVED" for c in pkg["known_conflicts"])

    # candidates só entram explicitamente, rotulados OBSERVED (§62/§63)
    pkg2 = client.get(
        "/context",
        params={"capability": "faturamento", "include_candidates": True},
        headers=ctx["admin"],
    ).json()
    labels = {i["id"]: i["label"] for i in pkg2["rules"]}
    assert labels[ids["rule_cand"]] == "OBSERVED"

    md = client.get(
        "/context",
        params={"capability": "faturamento", "format": "markdown"},
        headers=ctx["admin"],
    ).text
    assert "# Context Package" in md and "[UNKNOWN]" in md and "[UNRESOLVED]" in md


def test_projecao_bdd(client, ctx):
    g = client.get(f"/projections/bdd/{ctx['ids']['scenario']}", headers=ctx["admin"]).text
    assert "Scenario: Bloqueio de pedido com fatura vencida" in g
    assert "Given uma fatura vencida do cliente" in g
    assert "When o cliente tenta criar um pedido" in g
    assert "Then o pedido é rejeitado" in g

    feature = client.get(
        "/projections/bdd", params={"capability": "faturamento"}, headers=ctx["admin"]
    ).text
    assert feature.startswith("Feature: faturamento")
    assert "Scenario:" in feature


def test_projecao_decision_table(client, ctx):
    t = client.get(
        f"/projections/decision-table/{ctx['ids']['decision']}", headers=ctx["admin"]
    ).json()
    assert t["inputs"] == ["customer.risk", "order.amount"]
    assert t["output"] == "approval_level"
    assert len(t["rows"]) == 2 and t["rows"][1]["output"] == "director"


def test_projecao_state_machine(client, ctx):
    sm = client.get(
        "/projections/state-machine", params={"capability": "faturamento"},
        headers=ctx["admin"],
    ).json()
    assert {s["title"] for s in sm["states"]} == {"Aberta", "Paga"}
    t = sm["transitions"][0]
    assert t["from_title"] == "Aberta" and t["to_title"] == "Paga"
    assert t["trigger"] == "pagar_fatura" and t["conditions"] == [ctx["ids"]["rule"]]


def test_projecao_markdown(client, ctx):
    md = client.get(
        "/projections/markdown", params={"capability": "faturamento"}, headers=ctx["admin"]
    ).text
    assert "## Regras" in md and "Fatura vencida bloqueia novos pedidos" in md
