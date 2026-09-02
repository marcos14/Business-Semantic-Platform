"""Integração do kernel via API: lifecycle com audit, locks, gates e §123."""

import pytest


def _login(client, email, password="s3nha-teste"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ensure_user(client, admin, email, name, bindings):
    r = client.post(
        "/admin/users",
        json={"email": email, "name": name, "password": "s3nha-teste"},
        headers=admin,
    )
    if r.status_code == 201:
        user_id = r.json()["id"]
    else:
        users = client.get("/admin/users", headers=admin).json()
        user_id = next(u["id"] for u in users if u["email"] == email)
    for b in bindings:
        client.post("/admin/role-bindings", json={"user_id": user_id, **b}, headers=admin)
    return user_id


@pytest.fixture(scope="module")
def ctx(client):
    from app.create_admin import ensure_admin

    ensure_admin("admin@example.com", "Admin", "admin-s3nha")
    admin = _login(client, "admin@example.com", "admin-s3nha")
    client.post("/admin/domains", json={"slug": "fin", "name": "Finance"}, headers=admin)
    client.post(
        "/admin/capabilities",
        json={"slug": "ar", "domain_slug": "fin", "name": "Accounts Receivable"},
        headers=admin,
    )
    _ensure_user(
        client, admin, "rev@example.com", "Rev", [{"role": "reviewer", "domain_slug": "fin"}]
    )
    _ensure_user(
        client,
        admin,
        "owner@example.com",
        "Owner",
        [{"role": "decision_owner", "domain_slug": "fin"}],
    )
    _ensure_user(client, admin, "fora@example.com", "Fora", [])
    return {
        "admin": admin,
        "rev": _login(client, "rev@example.com"),
        "owner": _login(client, "owner@example.com"),
        "fora": _login(client, "fora@example.com"),
    }


def _nova_rule(client, ctx, title="Cancelled invoice cannot receive payment", **extra):
    payload = {
        "kind": "rule",
        "title": title,
        "domain": "fin",
        "capability": "ar",
        "scope": {"country": "BR"},
        "body": {"statement": title},
        **extra,
    }
    r = client.post("/knowledge/candidates", json=payload, headers=ctx["rev"])
    assert r.status_code == 201, r.text
    return r.json()


def _muda_status(client, headers, atom, novo, reason="teste"):
    return client.post(
        f"/knowledge/{atom['id']}/status",
        json={"status": novo, "reason": reason, "expected_lock_version": atom["lock_version"]},
        headers=headers,
    )


def test_lifecycle_completo_com_audit(client, ctx):
    atom = _nova_rule(client, ctx)
    assert atom["status"] == "CANDIDATE"
    assert atom["origin"] == "human"

    # evidence humana
    r = client.post(
        f"/knowledge/{atom['id']}/evidence",
        json={"type": "DOCUMENT", "summary": "Manual do módulo AR, seção 3.2"},
        headers=ctx["rev"],
    )
    assert r.status_code == 201

    for novo in ["READY_FOR_EVALUATION", "NEEDS_HUMAN_REVIEW", "IN_REVIEW", "DECISION_PENDING"]:
        r = _muda_status(client, ctx["rev"], atom, novo)
        assert r.status_code == 200, r.text
        atom = r.json()

    # AC-GOV-02: reviewer não canonicaliza
    r = _muda_status(client, ctx["rev"], atom, "CANONICAL")
    assert r.status_code == 403

    # AC-GOV-03: decision owner canonicaliza
    r = _muda_status(client, ctx["owner"], atom, "CANONICAL", reason="aprovado em revisão")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CANONICAL"

    # Audit (§69-§70): eventos completos + snapshots imutáveis
    hist = client.get(f"/knowledge/{atom['id']}/history", headers=ctx["rev"]).json()
    tipos = [e["type"] for e in hist["events"]]
    assert tipos[0] == "CandidateDiscovered"
    assert "EvidenceAdded" in tipos
    assert "HumanReviewRequested" in tipos
    assert tipos[-1] == "KnowledgeCanonicalized"
    troca = next(e for e in hist["events"] if e["type"] == "StatusChanged")
    assert {"from", "to", "reason"} <= set(troca["payload"])
    assert len(hist["versions"]) >= 5  # criação + 4 trocas de status no mínimo


def test_transicao_invalida_gera_409(client, ctx):
    atom = _nova_rule(client, ctx, title="Regra transição inválida")
    r = _muda_status(client, ctx["owner"], atom, "CANONICAL")  # pular o funil
    assert r.status_code == 409


def test_auto_approved_e_exclusivo_do_sistema(client, ctx):
    atom = _nova_rule(client, ctx, title="Regra auto approval")
    r = _muda_status(client, ctx["rev"], atom, "READY_FOR_EVALUATION")
    atom = r.json()
    r = _muda_status(client, ctx["owner"], atom, "AUTO_APPROVED")
    assert r.status_code == 400  # §86: só o Policy Engine (Fase 2)


def test_optimistic_locking(client, ctx):
    atom = _nova_rule(client, ctx, title="Regra lock otimista")
    # PATCH com lock desatualizado
    r = client.patch(
        f"/knowledge/{atom['id']}",
        json={"expected_lock_version": 99, "description": "x"},
        headers=ctx["rev"],
    )
    assert r.status_code == 409
    # §105: duas decisões simultâneas — a segunda com lock antigo falha
    r1 = _muda_status(client, ctx["rev"], atom, "READY_FOR_EVALUATION")
    assert r1.status_code == 200
    r2 = _muda_status(client, ctx["rev"], atom, "UNKNOWN")  # mesmo lock_version antigo
    assert r2.status_code == 409


def test_ac_evi_01_candidato_de_agente_sem_evidence(client, ctx):
    from app.db import SessionLocal
    from app.kernel.errors import EvidenceRequiredError
    from app.kernel.ir.envelope import AtomKind, Origin
    from app.services.knowledge import create_candidate

    with SessionLocal() as db:
        with pytest.raises(EvidenceRequiredError):
            create_candidate(
                db,
                actor="agent:code-discovery",
                origin=Origin.AGENT,
                kind=AtomKind.RULE,
                title="Regra sem evidência",
                domain="fin",
                capability="ar",
                body={"statement": "x"},
                evidence=[],
            )
        db.rollback()

    # Com evidence, passa — e a evidence fica vinculada
    with SessionLocal() as db:
        atom = create_candidate(
            db,
            actor="agent:code-discovery",
            origin=Origin.AGENT,
            kind=AtomKind.RULE,
            title="Regra com evidência de código",
            domain="fin",
            capability="ar",
            scope={"country": "BR"},
            body={"statement": "x"},
            evidence=[
                {
                    "type": "SOURCE_CODE",
                    "location": {"file": "InvoiceService.java", "start_line": 221, "end_line": 249},
                    "excerpt": "if (invoice.isCancelled()) throw ...",
                }
            ],
        )
        db.commit()
        atom_id = atom.id

    r = client.get(f"/knowledge/{atom_id}/evidence", headers=ctx["rev"])
    assert r.status_code == 200
    assert r.json()[0]["type"] == "SOURCE_CODE"


def test_canonical_desafiado_por_evidencia_contraditoria(client, ctx):
    atom = _nova_rule(client, ctx, title="Regra que será desafiada")
    for novo in ["READY_FOR_EVALUATION", "NEEDS_HUMAN_REVIEW", "IN_REVIEW", "DECISION_PENDING"]:
        atom = _muda_status(client, ctx["rev"], atom, novo).json()
    atom = _muda_status(client, ctx["owner"], atom, "CANONICAL").json()

    r = client.post(
        f"/knowledge/{atom['id']}/evidence",
        json={"type": "TEST", "summary": "Teste mostra o oposto", "relation": "contradicts"},
        headers=ctx["rev"],
    )
    assert r.status_code == 201

    # AC-CAN-03: canonical não muda automaticamente; desafio registrado
    atual = client.get(f"/knowledge/{atom['id']}", headers=ctx["rev"]).json()
    assert atual["status"] == "CANONICAL"
    hist = client.get(f"/knowledge/{atom['id']}/history", headers=ctx["rev"]).json()
    assert "CanonicalKnowledgeChallenged" in [e["type"] for e in hist["events"]]


def test_body_invalido_e_422(client, ctx):
    r = client.post(
        "/knowledge/candidates",
        json={"kind": "rule", "title": "Sem statement", "domain": "fin", "capability": "ar"},
        headers=ctx["rev"],
    )
    assert r.status_code == 422


def test_id_explicito_e_duplicata(client, ctx):
    payload = {
        "kind": "concept",
        "title": "Invoice",
        "domain": "fin",
        "capability": "ar",
        "id": "FIN.AR.CONCEPT.INVOICE",
    }
    r = client.post("/knowledge/candidates", json=payload, headers=ctx["rev"])
    assert r.status_code == 201
    r = client.post("/knowledge/candidates", json=payload, headers=ctx["rev"])
    assert r.status_code == 409
    # formato inválido
    r = client.post(
        "/knowledge/candidates",
        json={**payload, "id": "minusculas.invalidas"},
        headers=ctx["rev"],
    )
    assert r.status_code == 400


def test_id_gerado_automaticamente(client, ctx):
    r = client.post(
        "/knowledge/candidates",
        json={"kind": "concept", "title": "Payment", "domain": "fin", "capability": "ar"},
        headers=ctx["rev"],
    )
    assert r.status_code == 201
    assert r.json()["id"].startswith("FIN.AR.CONCEPT.")


def test_relacoes_e_referencia_quebrada(client, ctx):
    a = _nova_rule(client, ctx, title="Regra origem da relação")
    b = _nova_rule(client, ctx, title="Regra destino da relação")
    r = client.post(
        f"/knowledge/{a['id']}/relations",
        json={"to_atom": b["id"], "type": "DEPENDS_ON"},
        headers=ctx["rev"],
    )
    assert r.status_code == 201
    r = client.post(
        f"/knowledge/{a['id']}/relations",
        json={"to_atom": "FIN.AR.RULE.9999", "type": "AFFECTS"},
        headers=ctx["rev"],
    )
    assert r.status_code == 404


def test_rbac_escopado_no_kernel(client, ctx):
    # usuário sem binding em fin não cria candidate
    r = client.post(
        "/knowledge/candidates",
        json={"kind": "concept", "title": "X", "domain": "fin", "capability": "ar"},
        headers=ctx["fora"],
    )
    assert r.status_code == 403
    # mas pode ler (§7 Viewer)
    assert client.get("/knowledge", headers=ctx["fora"]).status_code == 200


def test_filtros_de_listagem(client, ctx):
    r = client.get(
        "/knowledge",
        params={"kind": "rule", "domain": "fin", "status": "CANONICAL"},
        headers=ctx["rev"],
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert all(i["kind"] == "rule" and i["status"] == "CANONICAL" for i in data["items"])


def test_source_registry(client, ctx):
    r = client.post(
        "/sources",
        json={
            "type": "source_code",
            "name": "praxis-autonomous",
            "repository": "C:/Projetos/praxis-autonomous",
            "branch": "auth",
            "domain_slug": "fin",
        },
        headers=ctx["admin"],
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    # reviewer não cria source
    r = client.post(
        "/sources", json={"type": "manual", "name": "x"}, headers=ctx["rev"]
    )
    assert r.status_code == 403
    # evidence referenciando a source
    atom = _nova_rule(client, ctx, title="Regra com source registrada")
    r = client.post(
        f"/knowledge/{atom['id']}/evidence",
        json={"type": "SOURCE_CODE", "source_id": source_id, "location": {"file": "x.go"}},
        headers=ctx["rev"],
    )
    assert r.status_code == 201
    ev = client.get(f"/knowledge/{atom['id']}/evidence", headers=ctx["rev"]).json()
    assert ev[0]["source_id"] == source_id


def test_linter_endpoint(client, ctx):
    # regra recém-criada sem evidence deve aparecer no lint
    _nova_rule(client, ctx, title="Regra sem evidencia para lint")
    r = client.get("/knowledge/lint", headers=ctx["rev"])
    assert r.status_code == 200
    codes = {f["code"] for f in r.json()["findings"]}
    assert "RULE_WITHOUT_EVIDENCE" in codes
