"""Governança (§36-§44): votos, decisão, inbox, kanban, notificações — AC-GOV-01..05, §105."""

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
    client.post("/admin/domains", json={"slug": "gov", "name": "Governança"}, headers=admin)
    client.post(
        "/admin/capabilities",
        json={"slug": "flow", "domain_slug": "gov", "name": "Flow"},
        headers=admin,
    )
    users = {
        "rev": ("g-rev@example.com", "reviewer"),
        "exp": ("g-exp@example.com", "domain_expert"),
        "own": ("g-own@example.com", "decision_owner"),
        "own2": ("g-own2@example.com", "decision_owner"),
    }
    ctx = {"admin": admin}
    for key, (email, role) in users.items():
        r = client.post(
            "/admin/users",
            json={"email": email, "name": key, "password": "s3nha-teste"},
            headers=admin,
        )
        client.post(
            "/admin/role-bindings",
            json={"user_id": r.json()["id"], "role": role, "domain_slug": "gov"},
            headers=admin,
        )
        ctx[key] = _login(client, email)
    client.post(
        "/admin/users",
        json={"email": "g-fora@example.com", "name": "Fora", "password": "s3nha-teste"},
        headers=admin,
    )
    ctx["fora"] = _login(client, "g-fora@example.com")
    return ctx


def _atom_em_revisao(client, ctx, title, risk=None, extra_evidence=None):
    """Candidate fraco de agente, avaliado → NEEDS_HUMAN_REVIEW."""
    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, Origin, RiskLevel
    from app.services.evaluation import evaluate_atom
    from app.services.knowledge import create_candidate

    evidence = [{"type": "SOURCE_CODE", "location": {"file": f"{title[:10]}.go"}}]
    if extra_evidence:
        evidence += extra_evidence
    with SessionLocal() as db:
        atom = create_candidate(
            db,
            actor="agent:test",
            origin=Origin.AGENT,
            kind=AtomKind.RULE,
            title=title,
            domain="gov",
            capability="flow",
            scope={"s": 1},
            risk=RiskLevel(risk) if risk else None,
            body={"statement": title},
            evidence=evidence,
        )
        db.flush()
        evaluate_atom(db, atom.id, trigger="teste")
        db.commit()
        return atom.id


def _room(client, ctx, atom_id, who="rev"):
    r = client.get(f"/reviews/{atom_id}", headers=ctx[who])
    assert r.status_code == 200, r.text
    return r.json()


def test_ac_gov_01_reviewer_pode_votar(client, ctx):
    atom_id = _atom_em_revisao(client, ctx, "Regra para voto do reviewer")
    r = client.post(
        f"/reviews/{atom_id}/vote",
        json={"action": "NEEDS_MORE_EVIDENCE", "comment": "quero runtime"},
        headers=ctx["rev"],
    )
    assert r.status_code == 201, r.text
    room = _room(client, ctx, atom_id)
    assert room["my_vote"] == "NEEDS_MORE_EVIDENCE"
    assert room["atom"]["status"] == "IN_REVIEW"  # primeiro voto abre a discussão


def test_ac_gov_02_reviewer_nao_canonicaliza(client, ctx):
    atom_id = _atom_em_revisao(client, ctx, "Regra que reviewer tenta aprovar")
    room = _room(client, ctx, atom_id)
    r = client.post(
        f"/reviews/{atom_id}/decision",
        json={
            "action": "APPROVE",
            "reason": "x",
            "expected_lock_version": room["atom"]["lock_version"],
        },
        headers=ctx["rev"],
    )
    assert r.status_code == 403


def test_jornada_humana_completa_ac_gov_03_04_05(client, ctx):
    """§100: votos → expert → decisão do owner → CANONICAL, com votos preservados."""
    atom_id = _atom_em_revisao(client, ctx, "Regra da jornada humana completa")

    # votos divergentes (AC-GOV-05: nada é apagado depois)
    client.post(
        f"/reviews/{atom_id}/vote",
        json={"action": "NEEDS_MORE_EVIDENCE", "comment": "faltou teste"},
        headers=ctx["rev"],
    )
    r = client.post(
        f"/reviews/{atom_id}/vote",
        json={"action": "CONFIRM", "comment": "confere com o código"},
        headers=ctx["exp"],
    )
    assert r.json()["domain_expert"] is True

    # §24: o voto assertivo do expert virou evidence DOMAIN_EXPERT
    room = _room(client, ctx, atom_id)
    tipos_ev = {e["type"] for e in room["evidence"]}
    assert "DOMAIN_EXPERT" in tipos_ev

    # resumo do owner (§44)
    assert room["summary"]["total_votes"] == 2
    assert room["summary"]["by_action"] == {"NEEDS_MORE_EVIDENCE": 1, "CONFIRM": 1}
    assert room["summary"]["domain_experts"] == {"CONFIRM": 1}
    assert room["summary"]["recommendation"] in (
        "CONFIRM",
        "CONFIRM_WITH_EXCEPTION",
        "NEEDS_MORE_EVIDENCE",
    )

    # pronto para decisão → notifica owner
    client.post(f"/reviews/{atom_id}/ready-for-decision", headers=ctx["exp"])
    notif = client.get("/notifications", params={"unread_only": True}, headers=ctx["own"]).json()
    assert any(n["type"] == "decision_needed" and n["atom_id"] == atom_id for n in notif["items"])

    # AC-GOV-03: owner aprova
    room = _room(client, ctx, atom_id, "own")
    assert room["permissions"]["can_decide"] is True
    r = client.post(
        f"/reviews/{atom_id}/decision",
        json={
            "action": "APPROVE",
            "reason": "aprovado após revisão",
            "expected_lock_version": room["atom"]["lock_version"],
        },
        headers=ctx["own"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CANONICAL"

    # AC-GOV-04/05: votos permanecem auditáveis e divergência preservada
    room = _room(client, ctx, atom_id)
    acoes = {v["action"] for v in room["votes"]}
    assert acoes == {"NEEDS_MORE_EVIDENCE", "CONFIRM"}
    hist = client.get(f"/knowledge/{atom_id}/history", headers=ctx["rev"]).json()
    assert [e for e in hist["events"] if e["type"] == "VoteSubmitted"]
    # aprovação do owner também é evidence (§24)
    assert any(
        e["type"] == "HUMAN_REVIEW" and "Owner" in (e["summary"] or "") for e in room["evidence"]
    )


def test_105_dois_owners_simultaneos(client, ctx):
    atom_id = _atom_em_revisao(client, ctx, "Regra disputada por dois owners")
    client.post(f"/reviews/{atom_id}/start", headers=ctx["rev"])
    room = _room(client, ctx, atom_id, "own")
    lock = room["atom"]["lock_version"]
    r1 = client.post(
        f"/reviews/{atom_id}/decision",
        json={"action": "APPROVE", "reason": "ok", "expected_lock_version": lock},
        headers=ctx["own"],
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"/reviews/{atom_id}/decision",
        json={"action": "REJECT", "reason": "não", "expected_lock_version": lock},
        headers=ctx["own2"],
    )
    assert r2.status_code == 409  # detect conflict + refresh (§105)


def test_voto_de_expert_sobe_confidence(client, ctx):
    atom_id = _atom_em_revisao(client, ctx, "Regra que ganha suporte humano")
    antes = client.get(f"/knowledge/{atom_id}/confidence", headers=ctx["rev"]).json()["score"]
    client.post(f"/reviews/{atom_id}/vote", json={"action": "CONFIRM"}, headers=ctx["exp"])
    depois = client.post(f"/knowledge/{atom_id}/evaluate", headers=ctx["rev"]).json()["score"]
    assert depois > antes  # human_support entrou no cálculo (§24 + §28)


def test_request_evidence_reabre_ciclo(client, ctx):
    atom_id = _atom_em_revisao(client, ctx, "Regra que precisa de mais evidência")
    client.post(f"/reviews/{atom_id}/start", headers=ctx["rev"])
    r = client.post(
        f"/reviews/{atom_id}/request-evidence",
        json={"note": "precisamos de runtime"},
        headers=ctx["rev"],
    )
    assert r.json()["status"] == "CORROBORATING"
    # nova evidência independente + reavaliação → roteia de novo
    client.post(
        f"/knowledge/{atom_id}/evidence",
        json={"type": "RUNTIME", "location": {"file": "trace-novo.log"}},
        headers=ctx["rev"],
    )
    s = client.post(f"/knowledge/{atom_id}/evaluate", headers=ctx["rev"]).json()
    assert s["routed"] is True


def test_inbox_priorizacao_e_escopo(client, ctx):
    critica = _atom_em_revisao(
        client,
        ctx,
        "Regra crítica com conflito",
        risk="CRITICAL",
        extra_evidence=[
            {"type": "TEST", "location": {"file": "x_test.go"}, "relation": "contradicts"}
        ],
    )
    baixa = _atom_em_revisao(client, ctx, "Regra de baixo risco", risk="LOW")
    inbox = client.get("/reviews/inbox", headers=ctx["rev"]).json()
    ids = [i["id"] for i in inbox["items"]]
    assert ids.index(critica) < ids.index(baixa)  # §85
    item = next(i for i in inbox["items"] if i["id"] == critica)
    assert item["priority"]["breakdown"]["risk"] == 4.0
    assert item["priority"]["breakdown"]["conflict_severity"] > 0
    assert inbox["summary"]["with_conflicts"] >= 1
    # fora do escopo: inbox vazia
    fora = client.get("/reviews/inbox", headers=ctx["fora"]).json()
    assert fora["items"] == []


def test_kanban_colunas(client, ctx):
    atom_id = _atom_em_revisao(client, ctx, "Regra no kanban")
    kb = client.get("/reviews/kanban", params={"domain": "gov"}, headers=ctx["rev"]).json()
    colunas = kb["columns"]
    assert set(colunas) == {
        "needs_review",
        "in_discussion",
        "needs_evidence",
        "needs_decision",
        "approved",
        "rejected",
    }
    assert any(c["id"] == atom_id for c in colunas["needs_review"])
    card = next(c for c in colunas["needs_review"] if c["id"] == atom_id)
    assert {"title", "confidence", "risk", "supporting_evidence", "conflicting_evidence"} <= set(
        card
    )


def test_notificacao_de_roteamento_e_mencao(client, ctx):
    atom_id = _atom_em_revisao(client, ctx, "Regra que gera notificações")
    notif = client.get("/notifications", headers=ctx["rev"]).json()
    alvo = next(
        n for n in notif["items"] if n["type"] == "review_needed" and n["atom_id"] == atom_id
    )
    # marcar lida
    r = client.post(f"/notifications/{alvo['id']}/read", headers=ctx["rev"])
    assert r.json()["read"] is True
    # menção em comentário notifica o mencionado (§73)
    client.post(
        f"/reviews/{atom_id}/comment",
        json={"text": "g-exp@example.com pode confirmar este comportamento?"},
        headers=ctx["rev"],
    )
    notif_exp = client.get(
        "/notifications", params={"unread_only": True}, headers=ctx["exp"]
    ).json()
    assert any(n["type"] == "mention" and n["atom_id"] == atom_id for n in notif_exp["items"])


def test_decisoes_reclassify_known_bug_e_excecao(client, ctx):
    atom_id = _atom_em_revisao(client, ctx, "Regra reclassificada")
    room = _room(client, ctx, atom_id, "own")
    r = client.post(
        f"/reviews/{atom_id}/decision",
        json={
            "action": "RECLASSIFY",
            "reason": "é comportamento observado",
            "expected_lock_version": room["atom"]["lock_version"],
            "classification": "OBSERVED_BEHAVIOR",
        },
        headers=ctx["own"],
    )
    assert r.status_code == 200
    assert (
        client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()["classification"]
        == "OBSERVED_BEHAVIOR"
    )

    bug_id = _atom_em_revisao(client, ctx, "Comportamento que é bug legado")
    room = _room(client, ctx, bug_id, "own")
    r = client.post(
        f"/reviews/{bug_id}/decision",
        json={
            "action": "MARK_KNOWN_BUG",
            "reason": "confirmado como bug",
            "expected_lock_version": room["atom"]["lock_version"],
        },
        headers=ctx["own"],
    )
    assert r.status_code == 200
    atom = client.get(f"/knowledge/{bug_id}", headers=ctx["rev"]).json()
    assert atom["status"] == "LEGACY_BUG" and atom["classification"] == "KNOWN_BUG"

    exc_alvo = _atom_em_revisao(client, ctx, "Regra que ganha exceção")
    room = _room(client, ctx, exc_alvo, "own")
    r = client.post(
        f"/reviews/{exc_alvo}/decision",
        json={
            "action": "ADD_EXCEPTION",
            "reason": "governo é exceção",
            "expected_lock_version": room["atom"]["lock_version"],
            "exception": {
                "title": "Cliente governo não passa por esta regra",
                "condition": "customer.type == GOVERNMENT",
            },
        },
        headers=ctx["own"],
    )
    assert r.status_code == 200
    excecoes = client.get(
        "/knowledge", params={"kind": "exception", "domain": "gov"}, headers=ctx["rev"]
    ).json()["items"]
    assert any(e["body"]["applies_to"] == exc_alvo for e in excecoes)


def test_fora_do_escopo_nao_vota(client, ctx):
    atom_id = _atom_em_revisao(client, ctx, "Regra fora do escopo do intruso")
    r = client.post(
        f"/reviews/{atom_id}/vote", json={"action": "CONFIRM"}, headers=ctx["fora"]
    )
    assert r.status_code == 403
