"""Régua de relevância: TRIVIAL nunca entra; LOW nunca ocupa revisor humano."""

from app.kernel.policy import (
    AUTO_APPROVED,
    AWAIT_EVIDENCE,
    NEEDS_HUMAN_REVIEW,
    EffectivePolicy,
    route,
)


def _policy(threshold=0.90) -> EffectivePolicy:
    p = EffectivePolicy(threshold=threshold)
    p.provenance["threshold"] = "teste"
    return p


def test_low_abaixo_da_regua_aguarda_evidencia_em_vez_de_humano():
    d = route(score=0.45, policy=_policy(), has_conflict=False, risk="LOW", lint_errors=0,
              significance="LOW", low_significance_threshold=0.60)
    assert d.outcome == AWAIT_EVIDENCE
    assert "baixa relevância" in d.reason


def test_low_com_regua_reduzida_auto_aprova():
    d = route(score=0.65, policy=_policy(), has_conflict=False, risk="LOW", lint_errors=0,
              significance="LOW", low_significance_threshold=0.60)
    assert d.outcome == AUTO_APPROVED
    conf = next(c for c in d.checks if c["check"] == "confidence_above_threshold")
    assert conf["passed"] and "régua reduzida" in conf["detail"]


def test_low_com_conflito_ou_risco_critico_ainda_vai_a_humano():
    d = route(score=0.45, policy=_policy(), has_conflict=True, risk="LOW", lint_errors=0,
              significance="LOW", low_significance_threshold=0.60)
    assert d.outcome == NEEDS_HUMAN_REVIEW
    d = route(score=0.95, policy=_policy(), has_conflict=False, risk="CRITICAL", lint_errors=0,
              significance="LOW", low_significance_threshold=0.60)
    assert d.outcome == NEEDS_HUMAN_REVIEW


def test_sistemico_aprova_sem_confianca_nem_politica():
    d = route(score=0.15, policy=_policy(), has_conflict=False, risk=None, lint_errors=0,
              significance="SYSTEMIC", low_significance_threshold=0.60)
    assert d.outcome == AUTO_APPROVED and "sistêmico" in d.reason
    assert any(c["check"] == "systemic_objective" and c["passed"] for c in d.checks)
    # política de revisão obrigatória também não se aplica ao sistêmico
    p = _policy()
    p.human_review_required = True
    d = route(score=0.15, policy=p, has_conflict=False, risk="LOW", lint_errors=0,
              significance="SYSTEMIC")
    assert d.outcome == AUTO_APPROVED


def test_sistemico_com_conflito_lint_ou_risco_critico_vai_a_humano():
    for kw in ({"has_conflict": True}, {"lint_errors": 1}, {"risk": "CRITICAL"}):
        base = dict(score=0.95, policy=_policy(), has_conflict=False, risk="LOW", lint_errors=0)
        d = route(**{**base, **kw}, significance="SYSTEMIC")
        assert d.outcome == NEEDS_HUMAN_REVIEW, kw
        assert "sistêmico, mas" in d.reason


def test_medium_e_high_seguem_fluxo_normal():
    for sig in ("MEDIUM", "HIGH", None):
        d = route(score=0.65, policy=_policy(), has_conflict=False, risk="LOW", lint_errors=0,
                  significance=sig, low_significance_threshold=0.60)
        assert d.outcome == NEEDS_HUMAN_REVIEW, sig
        d = route(score=0.95, policy=_policy(), has_conflict=False, risk="LOW", lint_errors=0,
                  significance=sig, low_significance_threshold=0.60)
        assert d.outcome == AUTO_APPROVED, sig


def test_regua_reduzida_nunca_sobe_o_threshold():
    d = route(score=0.55, policy=_policy(threshold=0.50), has_conflict=False, risk="LOW",
              lint_errors=0, significance="LOW", low_significance_threshold=0.60)
    assert d.outcome == AUTO_APPROVED  # política já era mais permissiva que a régua


def test_ingestao_grava_significance_e_low_vai_para_corroborating(client, tmp_path, monkeypatch):
    """Ponta a ponta com harness falso: LOW com pouca evidência → CORROBORATING, sem Inbox."""
    import subprocess
    import sys
    import uuid

    from sqlalchemy import select

    from app.config import settings
    from app.db import SessionLocal
    from app.models.auth import Capability, Domain
    from app.models.knowledge import KnowledgeAtom, Source
    from app.services.discovery import run_directed_discovery

    repo = tmp_path / "legado"
    repo.mkdir()
    (repo / "a.go").write_text("package a\n// regra\nfunc R() {}\nfunc S() {}\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "-A"], ["commit", "-q", "-m", "i"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    monkeypatch.setattr(settings, "discovery_workspace_mode", "inplace")
    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path / "logs"))
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    monkeypatch.setenv("FAKE_SCENARIO", "directed_ok")
    monkeypatch.setenv("FAKE_SIGNIFICANCE", "LOW")
    monkeypatch.setenv("FAKE_LINES", "2-3")  # a.go tem 4 linhas: a citação precisa existir
    fake = [sys.executable, str(__import__("pathlib").Path(__file__).parent / "fake_claude.py")]

    with SessionLocal() as db:
        if db.get(Domain, "sig") is None:
            db.add(Domain(slug="sig", name="Significance"))
            db.flush()
        if db.get(Capability, "sig-cap") is None:
            db.add(Capability(slug="sig-cap", domain_slug="sig", name="Cap"))
        src = Source(type="source_code", name=f"sig-{uuid.uuid4().hex[:6]}",
                     repository=str(repo), created_by="t")
        db.add(src)
        db.commit()
        run = run_directed_discovery(db, source_id=src.id, domain="sig", capability="sig-cap",
                                     file="a.go", actor="t", executable=fake)
        assert run.status == "succeeded", run.error
        assert run.candidates_created == 1
        atom = db.scalar(select(KnowledgeAtom).where(KnowledgeAtom.domain == "sig"))
        assert atom.significance == "LOW"
        # uma evidência só → confiança baixa → LOW não vai a humano
        assert atom.status == "CORROBORATING"
