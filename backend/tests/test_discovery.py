"""Discovery Engine com harness FALSO: runner, verificação de evidence, dedup, idempotência."""

import subprocess
import sys
import uuid
from pathlib import Path

import pytest

FAKE = [sys.executable, str(Path(__file__).parent / "fake_claude.py")]


# ---------- Runner (porta CodeAnalysisEngine) ----------


def _run_opts(tmp_path, **kw):
    from app.engines.claude_code import RunOptions

    return RunOptions(
        workdir=tmp_path,
        prompt="analise",
        logs_dir=tmp_path / "logs",
        label="teste",
        schema={"type": "object"},
        executable=FAKE,
        timeout_min=2,
        **kw,
    )


def test_runner_parse_resultado(tmp_path, monkeypatch):
    from app.engines import claude_code

    monkeypatch.setenv("FAKE_SCENARIO", "discovery_ok")
    res = claude_code.run(_run_opts(tmp_path))
    assert not res.is_error
    assert res.structured and "candidates" in res.structured
    assert res.cost_usd == 0.42
    assert res.session_id == "sess-fake-1"
    assert Path(res.log_path).exists()
    assert "fake" in res.cli_version


def test_runner_detecta_limite_de_franquia(tmp_path, monkeypatch):
    from app.engines import claude_code

    monkeypatch.setenv("FAKE_SCENARIO", "limit")
    res = claude_code.run(_run_opts(tmp_path))
    assert res.is_error and res.session_limit
    assert "reset" in (res.limit_detail or "").lower()


def test_runner_detecta_falha_de_autenticacao(tmp_path, monkeypatch):
    from app.engines import claude_code

    monkeypatch.setenv("FAKE_SCENARIO", "auth")
    res = claude_code.run(_run_opts(tmp_path))
    assert res.is_error and res.auth_failed


def test_runner_resgate_de_saida_estruturada(tmp_path, monkeypatch):
    from app.engines import claude_code

    monkeypatch.setenv("FAKE_SCENARIO", "rescue")
    res = claude_code.run(_run_opts(tmp_path))
    # resgate via --resume reaproveitou a sessão e somou custos (0.5 + 0.2)
    assert not res.is_error
    assert res.structured == {"ok": True}
    assert res.cost_usd == pytest.approx(0.7)


# ---------- Workspace + verificação de evidence ----------


@pytest.fixture()
def repo_legado(tmp_path):
    """Repositório git mínimo simulando a fonte legada."""
    repo = tmp_path / "legado"
    repo.mkdir()
    (repo / "billing.go").write_text(
        "package billing\n"
        "\n"
        "// JurosDiarios aplica 1% ao dia apos o vencimento\n"
        "func JurosDiarios(valor float64, diasAtraso int) float64 {\n"
        "    return valor * 0.01 * float64(diasAtraso)\n"
        "}\n",
        encoding="utf-8",
    )
    (repo / "billing_test.go").write_text(
        "package billing\n"
        "// TestJuros garante 1% ao dia\n"
        "func TestJuros(t *testing.T) {\n"
        "    // asserção de juros\n"
        "}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_workspace_e_leitura_verificada(repo_legado):
    from app.engines import workspace

    ws = workspace.create(str(repo_legado))
    try:
        assert len(ws.commit) == 40
        assert workspace.is_clean(ws)
        trecho = workspace.read_lines(ws, "billing.go", 3, 6)
        assert trecho is not None and "JurosDiarios" in trecho
        # citações inválidas
        assert workspace.read_lines(ws, "nao_existe.go", 1, 2) is None
        assert workspace.read_lines(ws, "billing.go", 5, 999) is None
        assert workspace.read_lines(ws, "../fora.txt", 1, 1) is None
    finally:
        workspace.destroy(ws)


# ---------- Serviço de discovery (integração com banco) ----------


@pytest.fixture()
def fonte(client, repo_legado):
    """Domain/capability/source deste módulo, via serviço."""
    from app.db import SessionLocal
    from app.models.auth import Capability, Domain
    from app.models.knowledge import Source

    with SessionLocal() as db:
        if db.get(Domain, "disc") is None:
            db.add(Domain(slug="disc", name="Discovery"))
            db.flush()
        if db.get(Capability, "billing") is None:
            db.add(Capability(slug="billing", domain_slug="disc", name="Billing"))
        src = Source(
            type="source_code",
            name=f"legado-{uuid.uuid4().hex[:6]}",
            repository=str(repo_legado),
            created_by="teste",
        )
        db.add(src)
        db.commit()
        return src.id


def test_discovery_ingestao_completa(client, fonte, monkeypatch, tmp_path):
    from app.config import settings
    from app.db import SessionLocal
    from app.services.discovery import run_discovery

    monkeypatch.setenv("FAKE_SCENARIO", "discovery_ok")
    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path / "logs"))

    with SessionLocal() as db:
        run = run_discovery(
            db, source_id=fonte, agent="code", domain="disc", capability="billing",
            actor="teste", executable=FAKE, timeout_min=2,
        )

    assert run.status == "succeeded"
    assert run.candidates_created == 1  # válida
    assert run.trivial_skipped == 1  # "data inicial > final": validação genérica, fora da régua
    assert run.candidates_rejected == 1  # citação alucinada descartou o candidate
    assert run.evidence_rejected == 1
    assert run.duplicates_skipped == 1  # duplicata exata
    assert run.questions_created == 1
    assert run.cost_usd == 0.42
    assert run.workspace_clean == "yes"
    assert run.commit and len(run.commit) == 40

    # o candidate criado: evidence com excerpt REAL do arquivo + avaliado/roteado
    from sqlalchemy import select

    from app.models.knowledge import Evidence, EvidenceLink, KnowledgeAtom

    with SessionLocal() as db:
        atom = db.scalar(
            select(KnowledgeAtom).where(
                KnowledgeAtom.domain == "disc", KnowledgeAtom.kind == "rule"
            )
        )
        assert atom is not None
        assert atom.origin == "agent"
        assert atom.status == "NEEDS_HUMAN_REVIEW"  # 1 evidência → roteado p/ humano
        assert atom.confidence is not None
        ev = db.scalar(
            select(Evidence)
            .join(EvidenceLink, EvidenceLink.evidence_id == Evidence.id)
            .where(EvidenceLink.atom_id == atom.id)
        )
        assert "JurosDiarios" in ev.excerpt  # trecho veio do arquivo real
        assert ev.location["commit"] == run.commit
        # question criada sem evidence (isenção P6)
        pergunta = db.scalar(
            select(KnowledgeAtom).where(
                KnowledgeAtom.domain == "disc", KnowledgeAtom.kind == "question"
            )
        )
        assert pergunta is not None


def test_discovery_idempotente(client, fonte, monkeypatch, tmp_path):
    from app.config import settings
    from app.db import SessionLocal
    from app.services.discovery import run_discovery

    monkeypatch.setenv("FAKE_SCENARIO", "discovery_ok")
    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path / "logs"))
    kwargs = dict(
        source_id=fonte, agent="code", domain="disc", capability="billing",
        actor="teste", executable=FAKE, timeout_min=2,
    )
    with SessionLocal() as db:
        r1 = run_discovery(db, **kwargs)
        id1 = r1.id
    with SessionLocal() as db:
        r2 = run_discovery(db, **kwargs)
    assert r2.id == id1  # mesmo (source, commit, agent, prompt) não repete


def test_discovery_limite_de_franquia(client, fonte, monkeypatch, tmp_path):
    from app.config import settings
    from app.db import SessionLocal
    from app.services.discovery import run_discovery

    monkeypatch.setenv("FAKE_SCENARIO", "limit")
    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path / "logs"))
    with SessionLocal() as db:
        run = run_discovery(
            db, source_id=fonte, agent="test", domain="disc", capability="billing",
            actor="teste", executable=FAKE, timeout_min=2,
        )
    assert run.status == "limit"


def test_corroboracao_adiciona_evidencia_independente(client, fonte, monkeypatch, tmp_path):
    from sqlalchemy import select

    from app.config import settings
    from app.db import SessionLocal
    from app.models.knowledge import Evidence, EvidenceLink, KnowledgeAtom
    from app.services.discovery import run_corroboration, run_discovery

    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path / "logs"))
    monkeypatch.setenv("FAKE_SCENARIO", "discovery_ok")
    with SessionLocal() as db:
        run_discovery(
            db, source_id=fonte, agent="code", domain="disc", capability="billing",
            actor="teste", executable=FAKE, timeout_min=2,
        )
        atom = db.scalar(
            select(KnowledgeAtom).where(
                KnowledgeAtom.domain == "disc", KnowledgeAtom.kind == "rule"
            )
        )
        atom_id = atom.id

    monkeypatch.setenv("FAKE_SCENARIO", "corrob_ok")
    monkeypatch.setenv("FAKE_ATOM_ID", atom_id)
    with SessionLocal() as db:
        run = run_corroboration(
            db, source_id=fonte, domain="disc", capability="billing",
            actor="teste", executable=FAKE, timeout_min=2,
        )
    assert run.status == "succeeded"

    with SessionLocal() as db:
        evs = db.scalars(
            select(Evidence)
            .join(EvidenceLink, EvidenceLink.evidence_id == Evidence.id)
            .where(EvidenceLink.atom_id == atom_id)
        ).all()
    criadores = {e.created_by for e in evs}
    tipos = {e.type for e in evs}
    assert any("corroboration" in c for c in criadores)  # segundo agente (§88)
    assert "TEST" in tipos  # evidência do teste, linhagem distinta
