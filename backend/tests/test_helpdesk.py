"""Vertical slice do PRD de Assistência Semântica para Help Desk."""

import pytest


def _login(client, email, password="s3nha-teste"):
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="module")
def hd(client):
    from app.create_admin import ensure_admin
    from app.db import SessionLocal
    from app.kernel.ir.envelope import (
        AtomKind,
        Classification,
        LifecycleStatus,
        Origin,
        RiskLevel,
        Significance,
    )
    from app.models.knowledge import KnowledgeAtom
    from app.services.knowledge import change_status, create_candidate, get_atom

    ensure_admin("hd-admin@example.com", "HD Admin", "admin-s3nha")
    admin = _login(client, "hd-admin@example.com", "admin-s3nha")
    client.post("/admin/domains", json={"slug": "hd", "name": "Help Desk"}, headers=admin)
    client.post(
        "/admin/capabilities",
        json={
            "slug": "cancelamento-hd",
            "domain_slug": "hd",
            "name": "Cancelamento",
            "description": "Cancelamento de documentos no ERP.",
        },
        headers=admin,
    )
    client.post("/admin/domains", json={"slug": "secreto", "name": "Secreto"}, headers=admin)
    client.post(
        "/admin/capabilities",
        json={"slug": "cap-secreta", "domain_slug": "secreto", "name": "Cap secreta"},
        headers=admin,
    )
    created = client.post(
        "/admin/users",
        json={"email": "hd-view@example.com", "name": "Viewer", "password": "s3nha-teste"},
        headers=admin,
    ).json()
    client.post(
        "/admin/role-bindings",
        json={"user_id": created["id"], "role": "viewer", "domain_slug": "hd"},
        headers=admin,
    )
    viewer = _login(client, "hd-view@example.com")

    evidence = [
        {
            "type": "SOURCE_CODE",
            "location": {
                "file": "Cancelamento.pas",
                "start_line": 10,
                "end_line": 18,
                "commit": "abc123",
                "symbol": "TFrmCancelamento.ValidarPrazo",
            },
            "summary": "A tela bloqueia cancelamentos realizados fora do prazo.",
            "excerpt": "if Dias > Prazo then raise ERegra.Create(MSG_CAN_014);",
            "metadata": {"mechanism": "VALIDATION"},
        }
    ]

    def atom(kind, title, body, *, canonical=False, confidence=0.75, scope=None):
        row = create_candidate(
            db,
            actor="agent:helpdesk-test",
            origin=Origin.AGENT,
            kind=kind,
            title=title,
            domain="hd",
            capability="cancelamento-hd",
            description=title,
            classification=Classification.OBSERVED_BEHAVIOR,
            risk=RiskLevel.MEDIUM,
            significance=Significance.MEDIUM,
            scope=scope,
            body=body,
            evidence=evidence,
        )
        db.flush()
        row.confidence = confidence
        if canonical:
            for status in (
                LifecycleStatus.READY_FOR_EVALUATION,
                LifecycleStatus.NEEDS_HUMAN_REVIEW,
                LifecycleStatus.IN_REVIEW,
                LifecycleStatus.DECISION_PENDING,
                LifecycleStatus.CANONICAL,
            ):
                current = get_atom(db, row.id)
                change_status(
                    db,
                    row.id,
                    actor="hd-admin@example.com",
                    new_status=status,
                    reason="fixture helpdesk",
                    expected_lock_version=current.lock_version,
                    authority_granted=status == LifecycleStatus.CANONICAL,
                )
        return row.id

    with SessionLocal() as db:
        ids = {}
        ids["message"] = atom(
            AtomKind.MESSAGE,
            "Cancelamento fora do prazo permitido",
            {
                "text": "Cancelamento fora do prazo permitido",
                "code": "CAN-014",
                "severity": "error",
                "channel": "ui",
                "meaning": "O prazo configurado para cancelamento foi excedido.",
            },
            canonical=True,
        )
        ids["procedure"] = atom(
            AtomKind.PROCEDURE,
            "Como cancelar uma nota elegível",
            {
                "goal": "Cancelar uma nota elegível",
                "prerequisites": ["A nota deve estar autorizada."],
                "steps": [
                    {
                        "order": 1,
                        "action": "Abrir a tela de cancelamento.",
                        "expected_result": "A nota é carregada.",
                    }
                ],
                "escalation_conditions": ["A mensagem CAN-014 continuar."],
            },
            canonical=True,
        )
        ids["scoped"] = atom(
            AtomKind.RULE,
            "Tenant A permite cancelamento em sete dias",
            {"statement": "No tenant A, o cancelamento é permitido por sete dias."},
            scope={"tenant": "A", "document_state": "autorizada"},
        )
        scoped = db.get(KnowledgeAtom, ids["scoped"])
        scoped.status = str(LifecycleStatus.PROVISIONAL)
        ids["candidate"] = atom(
            AtomKind.RULE,
            "Hipótese de parâmetro alternativo",
            {"statement": "Um parâmetro alternativo pode ampliar o prazo."},
            confidence=0.30,
        )
        ids["question"] = create_candidate(
            db,
            actor="agent:helpdesk-test",
            origin=Origin.AGENT,
            kind=AtomKind.QUESTION,
            title="O prazo muda por feriado?",
            domain="hd",
            capability="cancelamento-hd",
            body={"question": "O prazo muda por feriado?"},
        ).id
        # Atom que jamais pode aparecer para o viewer escopado em hd.
        ids["secret"] = create_candidate(
            db,
            actor="agent:helpdesk-test",
            origin=Origin.AGENT,
            kind=AtomKind.RULE,
            title="Segredo operacional",
            domain="secreto",
            capability="cap-secreta",
            body={"statement": "Conteúdo não autorizado."},
            evidence=evidence,
        ).id
        db.commit()
    return {"admin": admin, "viewer": viewer, "viewer_id": created["id"], "ids": ids}


def test_contexto_direct_recupera_mensagem_sem_vazar_codigo(client, hd):
    response = client.post(
        "/helpdesk/context",
        json={
            "question": "O que significa o erro CAN-014: cancelamento fora do prazo permitido?",
            "consumer_profile": "helpdesk_direct",
            "domain": "hd",
            "capability": "cancelamento-hd",
            "context": {"screen": "cancelamento", "error_messages": ["CAN-014"]},
        },
        headers=hd["viewer"],
    )
    assert response.status_code == 200, response.text
    package = response.json()
    ids = {item["id"] for item in package["knowledge"]}
    assert hd["ids"]["message"] in ids
    assert hd["ids"]["candidate"] not in ids
    message = next(item for item in package["knowledge"] if item["id"] == hd["ids"]["message"])
    assert message["label"] == "CANONICAL"
    assert all("excerpt" not in evidence for evidence in message["evidence_refs"])
    assert all("location" not in evidence for evidence in message["evidence_refs"])
    assert package["interaction_id"]
    assert package["recommended_action"] == "ANSWER"


def test_contexto_copilot_n3_inclui_hipoteses_e_evidencia_tecnica(client, hd):
    response = client.post(
        "/helpdesk/context",
        json={
            "question": "Qual parâmetro pode ampliar o prazo de cancelamento?",
            "consumer_profile": "helpdesk_copilot_n3",
            "domain": "hd",
            "capability": "cancelamento-hd",
            "context": {},
        },
        headers=hd["admin"],
    )
    assert response.status_code == 200, response.text
    package = response.json()
    candidate = next(
        item for item in package["knowledge"] if item["id"] == hd["ids"]["candidate"]
    )
    assert candidate["label"] == "OBSERVED"
    assert candidate["evidence_refs"][0]["excerpt"]
    assert candidate["evidence_refs"][0]["location"]["symbol"]
    assert any(question["id"] == hd["ids"]["question"] for question in package["open_questions"])

    forbidden = client.post(
        "/helpdesk/context",
        json={
            "question": "Mostre o código de cancelamento",
            "consumer_profile": "helpdesk_copilot_n3",
            "domain": "hd",
            "capability": "cancelamento-hd",
        },
        headers=hd["viewer"],
    )
    assert forbidden.status_code == 403


def test_scope_mismatch_exclui_e_contexto_ausente_pergunta(client, hd):
    mismatch = client.post(
        "/helpdesk/context",
        json={
            "question": "Qual é o prazo do tenant A?",
            "consumer_profile": "helpdesk_direct",
            "domain": "hd",
            "capability": "cancelamento-hd",
            "context": {"tenant": "B", "document_state": "autorizada"},
        },
        headers=hd["viewer"],
    ).json()
    assert hd["ids"]["scoped"] not in {item["id"] for item in mismatch["knowledge"]}

    missing = client.post(
        "/helpdesk/context",
        json={
            "question": "Qual é o prazo para cancelar?",
            "consumer_profile": "helpdesk_direct",
            "domain": "hd",
            "capability": "cancelamento-hd",
            "context": {"tenant": "A"},
        },
        headers=hd["viewer"],
    ).json()
    assert missing["recommended_action"] == "ASK_CLARIFYING"
    assert "estado atual" in " ".join(missing["clarifying_questions"]).lower()


def test_rbac_impede_domain_nao_autorizado(client, hd):
    response = client.post(
        "/helpdesk/context",
        json={
            "question": "Mostre o segredo operacional",
            "consumer_profile": "helpdesk_copilot_n3",
            "domain": "secreto",
            "capability": "cap-secreta",
        },
        headers=hd["viewer"],
    )
    assert response.status_code == 403
    assert client.get(f"/knowledge/{hd['ids']['secret']}", headers=hd["viewer"]).status_code == 403
    search = client.get("/search", params={"q": "Segredo operacional"}, headers=hd["viewer"])
    assert search.status_code == 200
    assert hd["ids"]["secret"] not in {item["id"] for item in search.json()["items"]}
    tree = client.get("/explorer", headers=hd["viewer"]).json()
    assert "secreto" not in {domain["slug"] for domain in tree}

    evidence = client.get(
        f"/knowledge/{hd['ids']['message']}/evidence", headers=hd["viewer"]
    )
    assert evidence.status_code == 200
    assert all("excerpt" not in item and "location" not in item for item in evidence.json())


def test_feedback_idempotente_e_correcao_vira_candidate(client, hd):
    package = client.post(
        "/helpdesk/context",
        json={
            "question": "Como cancelar uma nota?",
            "consumer_profile": "helpdesk_copilot_n1",
            "domain": "hd",
            "capability": "cancelamento-hd",
        },
        headers=hd["admin"],
    ).json()
    atom_id = package["knowledge"][0]["id"]
    payload = {
        "idempotency_key": "ticket-1-resolution",
        "outcome": "INCORRECT",
        "misleading_atom_ids": [atom_id],
        "correction": "O cancelamento também exige justificativa preenchida.",
        "ticket_reference": "TICKET-MASKED",
    }
    first = client.post(
        f"/helpdesk/interactions/{package['interaction_id']}/feedback",
        json=payload,
        headers=hd["admin"],
    )
    second = client.post(
        f"/helpdesk/interactions/{package['interaction_id']}/feedback",
        json=payload,
        headers=hd["admin"],
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["candidate_id"]

    metrics = client.get("/helpdesk/metrics", params={"domain": "hd"}, headers=hd["admin"])
    assert metrics.status_code == 200
    assert metrics.json()["by_outcome"]["INCORRECT"] >= 1


def test_contexto_geral_volta_a_ser_canonical_only_por_padrao(client, hd):
    strict = client.get(
        "/context", params={"capability": "cancelamento-hd"}, headers=hd["viewer"]
    ).json()
    ids = {
        item["id"]
        for section in ("rules", "messages", "procedures")
        for item in strict[section]
    }
    assert hd["ids"]["scoped"] not in ids
    assert strict["capability"]["description"]
    assert "messages" in strict and "procedures" in strict and "events" in strict


def test_policy_admin_e_avaliacao_retrieval(client, hd):
    policy = client.post(
        "/helpdesk/policies",
        json={
            "name": "Copilot N1 HD",
            "consumer_profile": "helpdesk_copilot_n1",
            "scope_type": "domain",
            "selector": "hd",
            "allowed_statuses": ["CANONICAL", "PROVISIONAL", "CANDIDATE"],
            "minimum_confidence": {},
            "allow_stale": True,
            "max_context_tokens": 6000,
        },
        headers=hd["admin"],
    )
    assert policy.status_code == 201, policy.text
    assert policy.json()["max_context_tokens"] == 6000

    result = client.post(
        "/helpdesk/evaluate",
        json={
            "consumer_profile": "helpdesk_copilot_n1",
            "cases": [
                {
                    "id": "HD-1",
                    "question": "O que significa CAN-014?",
                    "domain": "hd",
                    "capability": "cancelamento-hd",
                    "expected_atom_ids": [hd["ids"]["message"]],
                }
            ],
        },
        headers=hd["viewer"],
    )
    assert result.status_code == 200, result.text
    assert result.json()["recall_at_5"] == 1.0


def test_identidade_de_maquina_limita_profile_e_pseudonimiza_log(client, hd):
    created = client.post(
        "/helpdesk/clients",
        json={
            "name": "Bot de atendimento",
            "user_id": hd["viewer_id"],
            "allowed_profiles": ["helpdesk_direct"],
            "rate_limit_per_minute": 20,
        },
        headers=hd["admin"],
    )
    assert created.status_code == 201, created.text
    credential = created.json()
    machine = {"X-BSP-API-Key": credential["api_key"]}

    forbidden = client.post(
        "/helpdesk/context",
        json={
            "question": "Como cancelar?",
            "consumer_profile": "helpdesk_copilot_n3",
            "domain": "hd",
            "capability": "cancelamento-hd",
        },
        headers=machine,
    )
    assert forbidden.status_code == 403

    response = client.post(
        "/helpdesk/context",
        json={
            "question": "Cliente maria@example.com recebeu CAN-014, como cancelar?",
            "consumer_profile": "helpdesk_direct",
            "domain": "hd",
            "capability": "cancelamento-hd",
            "context": {"tenant": "empresa-123", "authorization": "segredo"},
        },
        headers=machine,
    )
    assert response.status_code == 200, response.text
    interaction = client.get(
        f"/helpdesk/interactions/{response.json()['interaction_id']}", headers=machine
    )
    assert interaction.status_code == 200, interaction.text
    audit = interaction.json()
    assert "maria@example.com" not in audit["question"]
    assert audit["request_context"]["tenant"].startswith("[TOKEN:")
    assert audit["request_context"]["authorization"] == "[REDACTED]"
    assert audit["resolved_context"]["dimensions"]["tenant"]["value"].startswith(
        "[TOKEN:"
    )

    revoked = client.delete(
        f"/helpdesk/clients/{credential['id']}", headers=hd["admin"]
    )
    assert revoked.status_code == 200
    denied = client.post(
        "/helpdesk/context",
        json={"question": "Como cancelar?", "consumer_profile": "helpdesk_direct"},
        headers=machine,
    )
    assert denied.status_code == 401


def test_freshness_compara_trecho_e_simbolo_em_git(client, hd, tmp_path):
    import subprocess

    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, EvidenceType, Origin
    from app.models.helpdesk import EvidenceFreshness
    from app.models.knowledge import Source
    from app.services.helpdesk import refresh_source_freshness
    from app.services.knowledge import create_candidate

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init")
    git("config", "user.email", "freshness@example.com")
    git("config", "user.name", "Freshness Test")
    source_file = tmp_path / "cancelamento.pas"
    source_file.write_text(
        "procedure Validar;\nbegin\n  BloquearCancelamento;\nend;\n",
        encoding="utf-8",
    )
    git("add", "cancelamento.pas")
    git("commit", "-m", "base")
    old_commit = git("rev-parse", "HEAD")

    with SessionLocal() as db:
        source = Source(
            type="SOURCE_CODE",
            name="freshness-test",
            repository=str(tmp_path),
            commit=old_commit,
            domain_slug="hd",
            created_by="test",
        )
        db.add(source)
        db.flush()
        atom = create_candidate(
            db,
            actor="test",
            origin=Origin.HUMAN,
            kind=AtomKind.RULE,
            title="Bloqueio de cancelamento",
            domain="hd",
            capability="cancelamento-hd",
            body={"statement": "O cancelamento pode ser bloqueado."},
            evidence=[
                {
                    "type": EvidenceType.SOURCE_CODE,
                    "source_id": str(source.id),
                    "location": {
                        "file": "cancelamento.pas",
                        "start_line": 1,
                        "end_line": 4,
                        "commit": old_commit,
                        "symbol": "Validar",
                    },
                    "excerpt": "procedure Validar;\nbegin\n  BloquearCancelamento;\nend;",
                    "summary": "A rotina bloqueia o cancelamento.",
                }
            ],
        )
        db.commit()

        source_file.write_text(
            "procedure Validar;\nbegin\n  BloquearCancelamento;\nend;\n// outra rotina\n",
            encoding="utf-8",
        )
        git("add", "cancelamento.pas")
        git("commit", "-m", "mudanca sem impacto")
        refresh_source_freshness(db, source=source)
        db.flush()
        evidence_id = atom.evidence_links[0].evidence_id
        assert db.get(EvidenceFreshness, evidence_id).status == "FRESH"

        source_file.write_text(
            "procedure Validar;\nbegin\n  PermitirCancelamento;\nend;\n",
            encoding="utf-8",
        )
        git("add", "cancelamento.pas")
        git("commit", "-m", "mudanca no simbolo")
        refresh_source_freshness(db, source=source)
        db.flush()
        assert db.get(EvidenceFreshness, evidence_id).status == "POTENTIALLY_STALE"

        source_file.write_text("procedure Outra;\nbegin\nend;\n", encoding="utf-8")
        git("add", "cancelamento.pas")
        git("commit", "-m", "remove simbolo")
        refresh_source_freshness(db, source=source)
        db.flush()
        assert db.get(EvidenceFreshness, evidence_id).status == "STALE"
