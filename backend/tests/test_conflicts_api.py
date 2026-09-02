"""Conflitos (§48-§50, §74) e Questions (§51): AC-CON-01..03, AC-CAN-03, decomposição (§47)."""

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
    client.post("/admin/domains", json={"slug": "cfl", "name": "Conflitos"}, headers=admin)
    client.post(
        "/admin/capabilities",
        json={"slug": "cap5", "domain_slug": "cfl", "name": "Cap5"},
        headers=admin,
    )
    ctx = {"admin": admin}
    for key, role in [("rev", "reviewer"), ("exp", "domain_expert"), ("own", "decision_owner")]:
        r = client.post(
            "/admin/users",
            json={"email": f"c-{key}@example.com", "name": key, "password": "s3nha-teste"},
            headers=admin,
        )
        client.post(
            "/admin/role-bindings",
            json={"user_id": r.json()["id"], "role": role, "domain_slug": "cfl"},
            headers=admin,
        )
        ctx[key] = _login(client, f"c-{key}@example.com")
    return ctx


def _rule(client, ctx, title, evaluate=False):
    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, Origin
    from app.services.evaluation import evaluate_atom
    from app.services.knowledge import create_candidate

    with SessionLocal() as db:
        atom = create_candidate(
            db, actor="agent:test", origin=Origin.AGENT, kind=AtomKind.RULE,
            title=title, domain="cfl", capability="cap5", scope={"s": 1},
            body={"statement": title},
            evidence=[{"type": "SOURCE_CODE", "location": {"file": f"{abs(hash(title))}.go"}}],
        )
        db.flush()
        if evaluate:
            evaluate_atom(db, atom.id, trigger="teste")
        db.commit()
        return atom.id


def _question(client, ctx, text):
    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, Origin
    from app.services.knowledge import create_candidate

    with SessionLocal() as db:
        q = create_candidate(
            db, actor="agent:test", origin=Origin.AGENT, kind=AtomKind.QUESTION,
            title=text, domain="cfl", capability="cap5", body={"question": text},
        )
        db.commit()
        return q.id


def _conflitos(client, ctx, state="open"):
    return client.get(
        "/conflicts", params={"domain": "cfl", "state": state}, headers=ctx["rev"]
    ).json()


class FakeProvider:
    def __init__(self, resposta):
        self.resposta = resposta

    def complete(self, *, system, user, max_tokens=1024):
        return self.resposta


# ---------- §48/§74: criação automática de conflito ----------


def test_evidencia_contraditoria_abre_conflito(client, ctx):
    atom_id = _rule(client, ctx, "Boleto vence em 30 dias corridos")
    r = client.post(
        f"/knowledge/{atom_id}/evidence",
        json={"type": "TEST", "summary": "Teste mostra 30 dias úteis", "relation": "contradicts"},
        headers=ctx["rev"],
    )
    assert r.status_code == 201
    abertos = [c for c in _conflitos(client, ctx) if c["about"] == atom_id]
    assert len(abertos) == 1
    atom = client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()
    assert atom["status"] == "CONFLICTED"

    # segunda contradição NÃO duplica o conflito
    client.post(
        f"/knowledge/{atom_id}/evidence",
        json={"type": "DOCUMENT", "summary": "Manual diverge", "relation": "contradicts"},
        headers=ctx["rev"],
    )
    assert len([c for c in _conflitos(client, ctx) if c["about"] == atom_id]) == 1

    # AC-CON-01: nada foi mesclado/apagado — as duas evidências contraditórias existem
    evs = client.get(f"/knowledge/{atom_id}/evidence", headers=ctx["rev"]).json()
    assert sum(1 for e in evs if e["relation"] == "contradicts") == 2


def test_ac_con_02_conflito_e_item_de_revisao(client, ctx):
    atom_id = _rule(client, ctx, "Regra que entra em conflito para a inbox")
    client.post(
        f"/knowledge/{atom_id}/evidence",
        json={"type": "TEST", "relation": "contradicts", "summary": "contradiz"},
        headers=ctx["rev"],
    )
    conflito = next(c for c in _conflitos(client, ctx) if c["about"] == atom_id)
    inbox_ids = [i["id"] for i in client.get("/reviews/inbox", headers=ctx["rev"]).json()["items"]]
    assert conflito["id"] in inbox_ids  # AC-CON-02
    assert atom_id in inbox_ids


# ---------- §50: resolução ----------


def _par_em_conflito(client, ctx, titulo_a, titulo_b):
    a = _rule(client, ctx, titulo_a)
    b = _rule(client, ctx, titulo_b)
    r = client.post(
        f"/knowledge/{a}/relations",
        json={"to_atom": b, "type": "CONTRADICTS"},
        headers=ctx["rev"],
    )
    assert r.status_code == 201
    r = client.post(
        "/conflicts/detect", json={"domain": "cfl", "capability": "cap5"}, headers=ctx["rev"]
    )
    assert r.status_code == 200
    conflito = next(
        c
        for c in _conflitos(client, ctx)
        if {x["atom_id"] for x in c["assertions"]} == {a, b}
    )
    return a, b, conflito


def test_ac_con_03_select_assertion(client, ctx):
    a, b, conflito = _par_em_conflito(
        client, ctx, "Cancelamento até o envio", "Cancelamento até o faturamento"
    )
    payload = {
        "action": "SELECT_ASSERTION",
        "reason": "código confirma envio",
        "expected_lock_version": conflito["lock_version"],
        "params": {"winner_atom_id": a},
    }
    # reviewer não resolve (AC-CON-03)
    assert client.post(
        f"/conflicts/{conflito['id']}/resolve", json=payload, headers=ctx["rev"]
    ).status_code == 403
    # lock desatualizado → 409 (§105)
    stale = {**payload, "expected_lock_version": 99}
    assert client.post(
        f"/conflicts/{conflito['id']}/resolve", json=stale, headers=ctx["own"]
    ).status_code == 409
    # owner resolve
    r = client.post(f"/conflicts/{conflito['id']}/resolve", json=payload, headers=ctx["own"])
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "resolved"
    assert client.get(f"/knowledge/{a}", headers=ctx["rev"]).json()["status"] == "DECISION_PENDING"
    assert client.get(f"/knowledge/{b}", headers=ctx["rev"]).json()["status"] == "REJECTED"
    # resolver de novo → erro (mas o conflito segue registrado — P7)
    assert client.post(
        f"/conflicts/{conflito['id']}/resolve", json=payload, headers=ctx["own"]
    ).status_code == 400


def test_jornada_101_split_by_scope(client, ctx):
    """§101: conflito → decisão 'varia por escopo' → duas regras com escopo → CANONICAL."""
    a, b, conflito = _par_em_conflito(
        client, ctx, "Desconto máximo de 10%", "Desconto máximo de 20%"
    )
    r = client.post(
        f"/conflicts/{conflito['id']}/resolve",
        json={
            "action": "SPLIT_BY_SCOPE",
            "reason": "a regra varia por segmento de cliente",
            "expected_lock_version": conflito["lock_version"],
            "params": {
                "splits": [
                    {"atom_id": a, "scope": {"customer_segment": "varejo"}},
                    {"atom_id": b, "scope": {"customer_segment": "atacado"}},
                ]
            },
        },
        headers=ctx["own"],
    )
    assert r.status_code == 200, r.text
    for atom_id, seg in [(a, "varejo"), (b, "atacado")]:
        atom = client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()
        assert atom["status"] == "DECISION_PENDING"
        assert atom["scope"] == {"customer_segment": seg}
        r = client.post(
            f"/reviews/{atom_id}/decision",
            json={
                "action": "APPROVE",
                "reason": "escopo definido no conflito",
                "expected_lock_version": atom["lock_version"],
            },
            headers=ctx["own"],
        )
        assert r.json()["status"] == "CANONICAL"


def test_resolucao_nunca_toca_canonical(client, ctx):
    """AC-CAN-03/§74: canonical desafiado reabre por processo, nunca por overwrite."""
    from app.db import SessionLocal
    from app.kernel.ir.envelope import LifecycleStatus as S
    from app.services.knowledge import change_status, get_atom

    atom_id = _rule(client, ctx, "Regra canonical que será desafiada")
    with SessionLocal() as db:
        for novo in [S.READY_FOR_EVALUATION, S.NEEDS_HUMAN_REVIEW, S.IN_REVIEW, S.DECISION_PENDING]:
            atom = get_atom(db, atom_id)
            change_status(db, atom_id, actor="c-own@example.com", new_status=novo,
                          reason="t", expected_lock_version=atom.lock_version)
        atom = get_atom(db, atom_id)
        change_status(db, atom_id, actor="c-own@example.com", new_status=S.CANONICAL,
                      reason="aprovada", expected_lock_version=atom.lock_version,
                      authority_granted=True)
        db.commit()

    r = client.post(
        f"/knowledge/{atom_id}/evidence",
        json={"type": "RUNTIME", "summary": "produção diverge", "relation": "contradicts"},
        headers=ctx["rev"],
    )
    assert r.status_code == 201

    atom = client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()
    assert atom["status"] == "CANONICAL"  # intocado
    conflito = next(c for c in _conflitos(client, ctx) if c["about"] == atom_id)
    assert conflito["reevaluation"] is True  # Reevaluation Request (§74)
    hist = client.get(f"/knowledge/{atom_id}/history", headers=ctx["rev"]).json()
    tipos = [e["type"] for e in hist["events"]]
    assert "CanonicalKnowledgeChallenged" in tipos
    notif = client.get("/notifications", headers=ctx["own"]).json()
    assert any(
        n["type"] == "canonical_challenged" and n["atom_id"] == atom_id for n in notif["items"]
    )

    # resolução que tentaria mudar o canonical é recusada
    r = client.post(
        f"/conflicts/{conflito['id']}/resolve",
        json={
            "action": "SELECT_ASSERTION",
            "reason": "x",
            "expected_lock_version": conflito["lock_version"],
            "params": {"winner_atom_id": atom_id},
        },
        headers=ctx["own"],
    )
    assert r.status_code == 400
    assert "supersede" in r.json()["detail"].lower()
    # mas MARK_UNRESOLVED registra sem esconder (P7)
    r = client.post(
        f"/conflicts/{conflito['id']}/resolve",
        json={
            "action": "MARK_UNRESOLVED",
            "reason": "aguardando análise fiscal",
            "expected_lock_version": conflito["lock_version"],
        },
        headers=ctx["own"],
    )
    assert r.status_code == 200 and r.json()["state"] == "unresolved"


def test_deteccao_llm(client, ctx, monkeypatch):
    a = _rule(client, ctx, "Prazo de estorno é 7 dias")
    b = _rule(client, ctx, "Prazo de estorno é 30 dias")
    import app.llm.provider as prov

    fake = FakeProvider(
        f'{{"pairs": [{{"a": "{a}", "b": "{b}", "topic": "prazo de estorno divergente"}},'
        f'{{"a": "ID.INVENTADO.X", "b": "{b}", "topic": "id alucinado"}}]}}'
    )
    monkeypatch.setattr(prov, "get_provider", lambda: fake)
    r = client.post(
        "/conflicts/detect",
        json={"domain": "cfl", "capability": "cap5", "use_llm": True},
        headers=ctx["rev"],
    )
    assert r.status_code == 200, r.text
    conflito = next(
        (c for c in _conflitos(client, ctx) if {x["atom_id"] for x in c["assertions"]} == {a, b}),
        None,
    )
    assert conflito is not None  # par válido criado; par com id inventado descartado


# ---------- §51: questions ----------


def test_fluxo_de_questions(client, ctx):
    q_id = _question(client, ctx, "Juros valem para boletos cancelados?")
    # reviewer não responde (§7.3: expert resolve)
    r = client.post(
        f"/questions/{q_id}/answer", json={"answer": "não"}, headers=ctx["rev"]
    )
    assert r.status_code == 403
    # expert responde
    r = client.post(
        f"/questions/{q_id}/answer",
        json={"answer": "Não: cancelamento remove a cobrança e os juros."},
        headers=ctx["exp"],
    )
    assert r.status_code == 200 and r.json()["answer"].startswith("Não")
    # atribuição notifica (§73)
    r = client.post(
        f"/questions/{q_id}/assign",
        json={"assignee_email": "c-exp@example.com"},
        headers=ctx["rev"],
    )
    assert r.status_code == 200
    notif = client.get("/notifications", headers=ctx["exp"]).json()
    assert any(n["type"] == "question_assigned" and n["atom_id"] == q_id for n in notif["items"])
    # converter em rule
    r = client.post(
        f"/questions/{q_id}/convert-to-rule",
        json={
            "title": "Boleto cancelado não acumula juros",
            "statement": "Juros não incidem sobre boletos cancelados.",
        },
        headers=ctx["exp"],
    )
    assert r.status_code == 201, r.text
    rule_id = r.json()["rule_id"]
    rule = client.get(f"/knowledge/{rule_id}", headers=ctx["rev"]).json()
    assert rule["kind"] == "rule" and rule["origin"] == "human"
    evs = client.get(f"/knowledge/{rule_id}/evidence", headers=ctx["rev"]).json()
    assert evs[0]["type"] == "DOMAIN_EXPERT"  # a resposta é a evidência (§24)
    listagem = client.get("/questions", params={"domain": "cfl"}, headers=ctx["rev"]).json()
    q = next(i for i in listagem if i["id"] == q_id)
    assert q["converted_to"] == rule_id
    # dupla conversão é recusada
    r = client.post(
        f"/questions/{q_id}/convert-to-rule",
        json={"title": "x", "statement": "y"},
        headers=ctx["exp"],
    )
    assert r.status_code == 400
    # filtro answered
    abertas = client.get(
        "/questions", params={"domain": "cfl", "answered": False}, headers=ctx["rev"]
    ).json()
    assert all(not i["answer"] for i in abertas)


# ---------- §47: decomposição ----------


def test_decomposicao(client, ctx, monkeypatch):
    atom_id = _rule(client, ctx, "Nota cancelada bloqueia operações financeiras", evaluate=True)
    import app.llm.provider as prov

    fake = FakeProvider(
        '{"rules": ['
        '{"title": "Nota cancelada não recebe pagamento",'
        ' "statement": "Pagamentos são rejeitados."},'
        '{"title": "Nota cancelada permite estorno", "statement": "Estornos continuam possíveis."}'
        "]}"
    )
    monkeypatch.setattr(prov, "get_provider", lambda: fake)
    r = client.post(f"/reviews/{atom_id}/suggest-decomposition", headers=ctx["rev"])
    assert r.status_code == 200
    sugestoes = r.json()["suggestions"]
    assert len(sugestoes) == 2

    atom = client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()
    corpo = {
        "rules": sugestoes,
        "reason": "granularidade",
        "expected_lock_version": atom["lock_version"],
    }
    # reviewer não aplica split (§43 é do owner)
    assert (
        client.post(f"/reviews/{atom_id}/decompose", json=corpo, headers=ctx["rev"]).status_code
        == 403
    )
    r = client.post(f"/reviews/{atom_id}/decompose", json=corpo, headers=ctx["own"])
    assert r.status_code == 201, r.text
    criadas = r.json()["created"]
    assert len(criadas) == 2
    assert client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()["status"] == "REJECTED"
    hist = client.get(f"/knowledge/{criadas[0]}/history", headers=ctx["rev"]).json()
    assert any(e["type"] == "RelationAdded" for e in hist["events"])
