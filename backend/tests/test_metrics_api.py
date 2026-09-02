"""Métricas (§75-§81, §107-§109) e eval §82 — módulo autossuficiente (domain `met`)."""

import pytest


def _login(client, email, password="s3nha-teste"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def ctx(client):
    """Fluxo completo próprio: auto-approval, 2 decisões humanas, conflito, question,
    e um canonical auto-aprovado depois DESAFIADO (para §80/§109)."""
    from app.create_admin import ensure_admin
    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, Origin
    from app.services.evaluation import evaluate_atom
    from app.services.knowledge import create_candidate

    ensure_admin("admin@example.com", "Admin", "admin-s3nha")
    admin = _login(client, "admin@example.com", "admin-s3nha")
    client.post("/admin/domains", json={"slug": "met", "name": "Metrics"}, headers=admin)
    client.post(
        "/admin/capabilities",
        json={"slug": "m7", "domain_slug": "met", "name": "M7"},
        headers=admin,
    )
    users = {}
    for key, role in [("rev", "reviewer"), ("own", "decision_owner")]:
        r = client.post(
            "/admin/users",
            json={"email": f"m-{key}@example.com", "name": key, "password": "s3nha-teste"},
            headers=admin,
        )
        client.post(
            "/admin/role-bindings",
            json={"user_id": r.json()["id"], "role": role, "domain_slug": "met"},
            headers=admin,
        )
        users[key] = _login(client, f"m-{key}@example.com")

    def _rule(db, title, evidence):
        a = create_candidate(
            db, actor="agent:test", origin=Origin.AGENT, kind=AtomKind.RULE,
            title=title, domain="met", capability="m7", scope={"s": 1},
            body={"statement": title}, evidence=evidence,
        )
        db.flush()
        evaluate_atom(db, a.id, trigger="teste")
        return a.id

    fraco = [{"type": "SOURCE_CODE", "location": {"file": "a.go"}}]
    forte = [
        {"type": "SOURCE_CODE", "location": {"file": "f1.go"}},
        {"type": "TEST", "location": {"file": "f1_test.go"}},
        {"type": "DOCUMENT", "location": {"file": "doc.md"}},
        {"type": "RUNTIME", "location": {"file": "trace.log"}},
    ]
    with SessionLocal() as db:
        a_id = _rule(db, "Regra aprovada por humano", fraco)
        b_id = _rule(db, "Regra rejeitada por humano", fraco)
        c_id = _rule(db, "Regra auto-aprovada e depois desafiada", forte)
        create_candidate(
            db, actor="agent:test", origin=Origin.AGENT, kind=AtomKind.QUESTION,
            title="Pergunta aberta de métrica", domain="met", capability="m7",
            body={"question": "Pergunta aberta de métrica?"},
        )
        db.commit()

    # jornada humana: voto → pronto p/ decisão → APPROVE (A) e REJECT (B)
    for atom_id, acao in [(a_id, "APPROVE"), (b_id, "REJECT")]:
        client.post(
            f"/reviews/{atom_id}/vote", json={"action": "CONFIRM"}, headers=users["rev"]
        )
        client.post(f"/reviews/{atom_id}/ready-for-decision", headers=users["rev"])
        atom = client.get(f"/knowledge/{atom_id}", headers=admin).json()
        r = client.post(
            f"/reviews/{atom_id}/decision",
            json={"action": acao, "reason": "métrica",
                  "expected_lock_version": atom["lock_version"]},
            headers=users["own"],
        )
        assert r.status_code == 200, r.text

    # C foi auto-aprovada (CANONICAL); desafiada por evidência contraditória (§74/§80)
    assert client.get(f"/knowledge/{c_id}", headers=admin).json()["status"] == "CANONICAL"
    client.post(
        f"/knowledge/{c_id}/evidence",
        json={"type": "RUNTIME", "relation": "contradicts", "summary": "produção diverge"},
        headers=users["rev"],
    )
    return {"admin": admin, **users, "ids": {"a": a_id, "b": b_id, "c": c_id}}


def test_semantic_coverage(client, ctx):
    cov = client.get("/metrics/coverage", params={"domain": "met"}, headers=ctx["admin"]).json()
    assert cov["rules_total"] == 3
    assert cov["canonical_atoms"] == 2  # A (humana) + C (auto)
    assert cov["auto_approved_atoms"] == 1
    assert cov["human_reviewed_atoms"] == 2  # A e B receberam voto
    assert cov["rules_with_evidence"] == 3
    assert cov["rules_with_multiple_independent_evidence"] >= 1  # C: 4 linhagens
    assert cov["open_questions"] == 1
    assert cov["open_conflicts"] == 1  # desafio da C abriu conflito de reavaliação
    assert cov["rules_without_owner"] == 0  # m-own cobre o domain
    assert cov["rules_without_scenarios"] == 3


def test_coverage_by_capability(client, ctx):
    linhas = client.get(
        "/metrics/coverage-by-capability", params={"domain": "met"}, headers=ctx["admin"]
    ).json()
    linha = next(r for r in linhas if r["capability"] == "m7")
    assert linha["canonical"] == 2 and linha["open_questions"] == 1


def test_confidence_distribution(client, ctx):
    d = client.get(
        "/metrics/confidence-distribution", params={"domain": "met"}, headers=ctx["admin"]
    ).json()
    assert set(d["buckets"]) == {"0-50", "50-70", "70-90", "90-95", "95-100"}
    assert sum(d["buckets"].values()) >= 3
    assert d["evaluated_atoms"] == 3
    assert d["pct_auto_approved"] == pytest.approx(1 / 3, abs=0.01)
    assert abs(d["pct_auto_approved"] + d["pct_needs_human"] - 1) < 0.001


def test_attention_kpis(client, ctx):
    k = client.get("/metrics/attention", params={"domain": "met"}, headers=ctx["admin"]).json()
    assert k["sent_to_human_review"] == 2  # A e B
    assert k["owner_decisions"] == 2
    assert k["median_review_latency_min"] is not None  # §77-§78 (wall-clock)
    assert k["automation_rate"] == pytest.approx(1 / 3, abs=0.01)  # §79
    assert k["false_auto_approval_rate"] == 1.0  # §80: única auto-aprovada foi desafiada
    assert k["votes_per_reviewer"]
    assert k["pct_rejected"] == 0.5
    assert k["pct_approved_unchanged"] == 0.5


def test_audit_dashboard(client, ctx):
    a = client.get("/metrics/audit", params={"domain": "met"}, headers=ctx["admin"]).json()
    assert a["auto_approved"] == 1
    assert a["human_approved"] == 1
    assert a["rejected"] == 1
    assert a["reopened_canonical"] == 1
    # §31: abaixo de 90% nunca houve auto-approval
    for faixa, contagens in a["threshold_performance"].items():
        if faixa != "90-100":
            assert contagens["AUTO_APPROVED"] == 0, (faixa, contagens)


def test_recent_events(client, ctx):
    evs = client.get("/metrics/recent-events", headers=ctx["admin"]).json()
    assert len(evs) > 5 and {"type", "actor", "at"} <= set(evs[0])


# ---------- §82: eval runner com provider falso ----------


class FakeEvalProvider:
    """1ª chamada = respondente; 2ª = juiz."""

    def __init__(self, answers_json, judge_json):
        self.calls = 0
        self.answers_json = answers_json
        self.judge_json = judge_json

    def complete(self, *, system, user, max_tokens=1024):
        self.calls += 1
        return self.answers_json if self.calls == 1 else self.judge_json


def test_eval_runner(client, ctx, tmp_path, monkeypatch):
    from app.config import settings
    from app.db import SessionLocal
    from app.services.evaluator import run_eval

    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path))
    gold = tmp_path / "gold.yaml"
    gold.write_text(
        """
questions:
  - id: G1
    question: Regras aprovadas bloqueiam algo?
    expected_answer: Sim, a regra aprovada por humano vale.
    expected_kind: defined
  - id: G2
    question: Qual o prazo de expurgo?
    expected_answer: NÃO DEFINIDO — resposta correta é UNKNOWN.
    expected_kind: unknown
  - id: G3
    question: Existe multa por atraso?
    expected_answer: NÃO DEFINIDO — resposta correta é UNKNOWN.
    expected_kind: unknown
""",
        encoding="utf-8",
    )
    fake = FakeEvalProvider(
        '{"answers": [{"id": "G1", "answer": "Sim, a regra vale."},'
        ' {"id": "G2", "answer": "NÃO SEI"},'
        ' {"id": "G3", "answer": "A multa é de 2% ao mês."}]}',
        '{"results": [{"id": "G1", "classification": "CORRECT", "note": "ok"},'
        ' {"id": "G2", "classification": "UNKNOWN_CORRECTLY_IDENTIFIED", "note": "ok"},'
        ' {"id": "G3", "classification": "HALLUCINATED", "note": "inventou multa"}]}',
    )
    with SessionLocal() as db:
        s = run_eval(db, gold_path=gold, capability="m7", llm_provider=fake)
    assert s["total_questions"] == 3
    assert s["counts"]["CORRECT"] == 1
    assert s["counts"]["UNKNOWN_CORRECTLY_IDENTIFIED"] == 1
    assert s["counts"]["HALLUCINATED"] == 1  # §83 detectada
    assert s["accuracy_strict"] == pytest.approx(2 / 3, abs=0.01)
    assert s["package_stats"]["canonical"] == 2  # respondente só viu canonical (AC-CTX-02)
    from pathlib import Path

    assert Path(s["report_path"]).exists()
