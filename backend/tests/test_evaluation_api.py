"""Integração: sinais → score → política → roteamento → audit (§86-§87, §99)."""

import pytest


def _login(client, email, password="s3nha-teste"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def ctx(client):
    from app.create_admin import ensure_admin

    ensure_admin("admin@example.com", "Admin", "admin-s3nha")
    admin = _login(client, "admin@example.com", "admin-s3nha")
    client.post("/admin/domains", json={"slug": "eva", "name": "Evaluation"}, headers=admin)
    for cap in ("cobranca", "fiscal"):
        client.post(
            "/admin/capabilities",
            json={"slug": cap, "domain_slug": "eva", "name": cap.title()},
            headers=admin,
        )
    r = client.post(
        "/admin/users",
        json={"email": "eva-rev@example.com", "name": "Rev", "password": "s3nha-teste"},
        headers=admin,
    )
    user_id = r.json()["id"]
    client.post(
        "/admin/role-bindings",
        json={"user_id": user_id, "role": "reviewer", "domain_slug": "eva"},
        headers=admin,
    )
    return {"admin": admin, "rev": _login(client, "eva-rev@example.com")}


def _candidato_agente(capability, title, evidence, risk=None):
    """Candidate origin=agent via serviço (o caminho da API de agentes chega na Fase 4)."""
    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, Origin, RiskLevel
    from app.services.knowledge import create_candidate

    with SessionLocal() as db:
        atom = create_candidate(
            db,
            actor="agent:code-discovery",
            origin=Origin.AGENT,
            kind=AtomKind.RULE,
            title=title,
            domain="eva",
            capability=capability,
            scope={"country": "BR"},
            risk=RiskLevel(risk) if risk else None,
            body={"statement": title},
            evidence=evidence,
        )
        db.commit()
        return atom.id


EVIDENCIA_FORTE = [
    {"type": "SOURCE_CODE", "location": {"file": "a.go"}},
    {"type": "TEST", "location": {"file": "a_test.go"}},
    {"type": "DOCUMENT", "location": {"file": "docs/manual.md"}},
    {"type": "RUNTIME", "location": {"file": "trace.log"}},
]


def test_caminho_automatico_ate_canonical(client, ctx):
    """§99: evidência forte → auto-approval → CANONICAL, sem humano interrompido."""
    atom_id = _candidato_agente("cobranca", "Boleto vencido gera juros diários", EVIDENCIA_FORTE)
    r = client.post(f"/knowledge/{atom_id}/evaluate", headers=ctx["rev"])
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["score"] >= 0.90
    assert s["decision"] == "AUTO_APPROVED"
    assert s["status"] == "CANONICAL"

    # Audit §87: DecisionMade com confidence, threshold/policy, evidence, versões
    hist = client.get(f"/knowledge/{atom_id}/history", headers=ctx["rev"]).json()
    tipos = [e["type"] for e in hist["events"]]
    assert "ConfidenceChanged" in tipos
    assert "KnowledgeCanonicalized" in tipos
    decisao = next(e for e in hist["events"] if e["type"] == "DecisionMade")
    assert decisao["payload"]["decision"] == "AUTO_APPROVED"
    assert decisao["payload"]["confidence"] >= 0.90
    assert decisao["payload"]["policy"]["threshold"] == 0.90
    assert len(decisao["payload"]["evidence"]) == 4
    from app.kernel.confidence import ENGINE_VERSION

    assert decisao["payload"]["engine_version"] == ENGINE_VERSION
    # cadeia de status completa
    trocas = [e["payload"] for e in hist["events"] if e["type"] == "StatusChanged"]
    assert [t["to"] for t in trocas] == ["READY_FOR_EVALUATION", "AUTO_APPROVED", "CANONICAL"]


def test_evidencia_fraca_vai_para_humano(client, ctx):
    atom_id = _candidato_agente(
        "cobranca",
        "Regra com uma única evidência",
        [{"type": "SOURCE_CODE", "location": {"file": "b.go"}}],
    )
    s = client.post(f"/knowledge/{atom_id}/evaluate", headers=ctx["rev"]).json()
    assert s["decision"] == "NEEDS_HUMAN_REVIEW"
    assert s["status"] == "NEEDS_HUMAN_REVIEW"
    assert "confidence" in s["reason"]


def test_politica_obrigatoria_vence_evidencia_forte(client, ctx):
    """AC-CONF-03 via API: fiscal exige humano mesmo com confidence alta (§33)."""
    r = client.post(
        "/admin/policies",
        json={
            "name": "Fiscal rules — human approval",
            "scope_type": "capability",
            "selector": "fiscal",
            "human_review_required": True,
        },
        headers=ctx["admin"],
    )
    assert r.status_code == 201, r.text
    policy_id = r.json()["id"]
    try:
        atom_id = _candidato_agente("fiscal", "Regra fiscal com evidência forte", EVIDENCIA_FORTE)
        s = client.post(f"/knowledge/{atom_id}/evaluate", headers=ctx["rev"]).json()
        assert s["score"] >= 0.90
        assert s["decision"] == "NEEDS_HUMAN_REVIEW"
        assert "no_mandatory_human_policy" in s["reason"]
        assert "Fiscal rules" in s["policy"]["provenance"]["human_review_required"]
    finally:
        client.delete(f"/admin/policies/{policy_id}", headers=ctx["admin"])


def test_risk_critical_bloqueia_auto_approval(client, ctx):
    atom_id = _candidato_agente(
        "cobranca", "Regra crítica com evidência forte", EVIDENCIA_FORTE, risk="CRITICAL"
    )
    s = client.post(f"/knowledge/{atom_id}/evaluate", headers=ctx["rev"]).json()
    assert s["decision"] == "NEEDS_HUMAN_REVIEW"
    assert "no_critical_risk" in s["reason"]


def test_recalcular_nao_reescreve_historico(client, ctx):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models.confidence import ConfidenceScore

    atom_id = _candidato_agente(
        "cobranca",
        "Regra para reavaliação",
        [{"type": "SOURCE_CODE", "location": {"file": "c.go"}}],
    )
    client.post(f"/knowledge/{atom_id}/evaluate", headers=ctx["rev"])
    # nova evidência → nova avaliação (em NEEDS_HUMAN_REVIEW: recalcula, sem re-rotear)
    client.post(
        f"/knowledge/{atom_id}/evidence",
        json={"type": "TEST", "location": {"file": "c_test.go"}},
        headers=ctx["rev"],
    )
    s2 = client.post(f"/knowledge/{atom_id}/evaluate", headers=ctx["rev"]).json()
    assert s2["routed"] is False

    with SessionLocal() as db:
        scores = db.scalars(
            select(ConfidenceScore)
            .where(ConfidenceScore.atom_id == atom_id)
            .order_by(ConfidenceScore.computed_at)
        ).all()
    assert len(scores) == 2  # append-only
    assert scores[1].score > scores[0].score

    conf = client.get(f"/knowledge/{atom_id}/confidence", headers=ctx["rev"]).json()
    assert conf["score"] == s2["score"]
    assert len(conf["signals"]) == 12
