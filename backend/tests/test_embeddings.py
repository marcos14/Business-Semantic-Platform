"""Recuperação e deduplicação semântica (pgvector) com provider FAKE e harness FALSO:
o turno dirigido recebe os candidates próximos, reforça em vez de duplicar, e a ingestão
marca/pula duplicatas por similaridade vetorial."""

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

FAKE = [sys.executable, str(Path(__file__).parent / "fake_claude.py")]
DOMAIN = "emb"
CAP = "emb-cobranca"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "legado"
    r.mkdir()
    (r / "billing.go").write_text(
        "package billing\n\n// JurosDiarios aplica 1% ao dia apos o vencimento\n"
        "func JurosDiarios(valor float64, diasAtraso int) float64 {\n"
        "    return valor * 0.01 * float64(diasAtraso)\n}\n",
        encoding="utf-8",
    )
    (r / "billing_test.go").write_text(
        "package billing\n// TestJuros garante 1% ao dia\nfunc TestJuros(t *testing.T) {\n}\n",
        encoding="utf-8",
    )
    (r / "outro.go").write_text("package outro\n// regra distinta\nfunc X() {}\n", encoding="utf-8")
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r


def _make_fonte(repo, domain: str, cap: str):
    from app.db import SessionLocal
    from app.models.auth import Capability, Domain
    from app.models.knowledge import Source

    with SessionLocal() as db:
        if db.get(Domain, domain) is None:
            db.add(Domain(slug=domain, name=f"Embeddings {domain}"))
            db.flush()
        if db.get(Capability, cap) is None:
            db.add(Capability(slug=cap, domain_slug=domain, name="Cobrança",
                              description="juros, boletos e cobrança"))
        src = Source(type="source_code", name=f"emb-{uuid.uuid4().hex[:6]}",
                     repository=str(repo), created_by="teste")
        db.add(src)
        db.commit()
        return src.id


@pytest.fixture()
def fonte(client, repo):
    return _make_fonte(repo, DOMAIN, CAP)


@pytest.fixture()
def fonte_isolada(client, repo):
    """Domain próprio: a dedup vetorial olha o domain inteiro, então este teste não pode
    enxergar os atoms criados pelos outros testes do módulo."""
    return _make_fonte(repo, "emb-iso", "emb-iso-cobranca")


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "embedding_provider", "fake")
    monkeypatch.setattr(settings, "discovery_workspace_mode", "inplace")
    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path / "logs"))
    monkeypatch.setenv("FAKE_CAP", CAP)
    monkeypatch.delenv("FAKE_REINFORCE", raising=False)


def test_provider_fake_e_determinista_e_captura_similaridade():
    from app.llm.embeddings import FakeEmbeddings

    p = FakeEmbeddings()
    a, b, c = p.embed([
        "Boleto vencido acumula juros de 1% ao dia",
        "Boleto vencido acumula juros de 1% ao dia sobre o valor",
        "Nota fiscal cancelada não gera comissão",
    ])
    def dot(x, y):
        return sum(i * j for i, j in zip(x, y, strict=True))
    assert dot(a, a) == pytest.approx(1.0)
    assert dot(a, b) > 0.8 > dot(a, c)
    assert p.embed(["x"]) == p.embed(["x"])


def test_ensure_embeddings_e_similar_atoms(client, fonte):
    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, Origin
    from app.models.embeddings import AtomEmbedding
    from app.services import embeddings as embsvc
    from app.services.knowledge import create_candidate

    with SessionLocal() as db:
        ev = [{"type": "SOURCE_CODE", "location": {"file": "billing.go"}, "source_id": fonte}]
        a1 = create_candidate(db, actor="t", origin=Origin.AGENT, kind=AtomKind.RULE,
                              title="Juros diários", domain=DOMAIN, capability=CAP,
                              body={"statement": "Boleto vencido acumula juros de 1% ao dia"},
                              evidence=ev)
        a2 = create_candidate(db, actor="t", origin=Origin.AGENT, kind=AtomKind.RULE,
                              title="Comissão", domain=DOMAIN, capability=CAP,
                              body={"statement": "Nota fiscal cancelada não gera comissão"},
                              evidence=ev)
        db.commit()
        n = embsvc.ensure_atom_embeddings(db, domain=DOMAIN)
        db.commit()
        assert n >= 2
        assert db.get(AtomEmbedding, a1.id) is not None
        assert embsvc.ensure_atom_embeddings(db, domain=DOMAIN) == 0  # idempotente

        qv = embsvc.embed_texts(["juros de boleto vencido por dia"])[0]
        prox = embsvc.similar_atoms(db, qv, domain=DOMAIN, capability=CAP, k=5)
        assert prox[0][0].id == a1.id and prox[0][1] > 0
        assert a2.id in {a.id for a, _ in prox}
        assert embsvc.similar_atoms(db, qv, domain="outro-domain") == []


def test_turno_dirigido_recebe_existentes_reforca_e_deduplica(client, fonte, monkeypatch):
    from app.db import SessionLocal
    from app.models.embeddings import AtomEmbedding
    from app.models.knowledge import EvidenceLink, KnowledgeAtom
    from app.services.discovery import run_directed_discovery

    monkeypatch.setenv("FAKE_SCENARIO", "directed_ok")
    batch = uuid.uuid4()
    with SessionLocal() as db:
        # 1º turno: cria a regra e grava o embedding no mesmo lote
        r1 = run_directed_discovery(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, file="billing.go",
            actor="t", batch_id=batch, executable=FAKE,
        )
        assert r1.status == "succeeded", r1.error
        assert r1.candidates_created == 1 and r1.reinforcements == 0
        atom = db.scalar(
            select(KnowledgeAtom).where(KnowledgeAtom.title == "Regra dirigida em billing.go")
        )
        assert atom is not None and db.get(AtomEmbedding, atom.id) is not None
        ev_antes = db.scalar(
            select(func.count()).select_from(EvidenceLink).where(EvidenceLink.atom_id == atom.id)
        )

        # 2º turno em outro arquivo: o fake devolve uma afirmação quase igual (só muda o
        # nome do arquivo/linhas) → dedup vetorial marca potencial duplicata, não pula
        monkeypatch.setenv("FAKE_LINES", "2-3")
        r2 = run_directed_discovery(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, file="outro.go",
            actor="t", batch_id=batch, executable=FAKE,
        )
        assert r2.status == "succeeded", r2.error
        assert r2.candidates_created == 1 and r2.potential_duplicates == 1

        # 3º turno: o agente RECONHECE a regra existente e reforça com evidência do teste
        monkeypatch.setenv("FAKE_REINFORCE", atom.id)
        monkeypatch.setenv("FAKE_LINES", "2-3")
        r3 = run_directed_discovery(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, file="billing_test.go",
            actor="t", batch_id=batch, executable=FAKE,
        )
        assert r3.status == "succeeded", r3.error
        assert r3.reinforcements == 1
        ev_depois = db.scalar(
            select(func.count()).select_from(EvidenceLink).where(EvidenceLink.atom_id == atom.id)
        )
        assert ev_depois == ev_antes + 1

        # reforço para atom inexistente/outro domain é rejeitado, não estoura
        monkeypatch.setenv("FAKE_REINFORCE", "NAO.EXISTE.RULE.0001")
        r4 = run_directed_discovery(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, file="billing_test.go",
            start_line=1, end_line=2, actor="t", batch_id=batch, executable=FAKE,
        )
        assert r4.status == "succeeded" and r4.reinforcements == 0 and r4.candidates_rejected >= 1


def test_dedup_vetorial_pula_afirmacao_quase_identica(client, fonte_isolada, monkeypatch):
    """Hash textual só pega statement idêntico; o vetor pega a mesma frase com outro nome de
    arquivo/linhas (fake BOW: ~0.9 de similaridade)."""
    from app.config import settings
    from app.db import SessionLocal
    from app.services.discovery import run_directed_discovery

    dom, cap = "emb-iso", "emb-iso-cobranca"
    monkeypatch.setenv("FAKE_SCENARIO", "directed_ok")
    monkeypatch.setattr(settings, "dedup_skip_similarity", 0.60)
    with SessionLocal() as db:
        r1 = run_directed_discovery(db, source_id=fonte_isolada, domain=dom, capability=cap,
                                    file="billing.go", actor="t", executable=FAKE)
        assert r1.status == "succeeded", r1.error
        assert r1.candidates_created == 1
        monkeypatch.setenv("FAKE_LINES", "2-3")
        r2 = run_directed_discovery(db, source_id=fonte_isolada, domain=dom, capability=cap,
                                    file="outro.go", actor="t", executable=FAKE)
        assert r2.status == "succeeded", r2.error
        assert r2.candidates_created == 0 and r2.duplicates_skipped == 1


def test_prompt_dirigido_inclui_conhecimento_existente():
    from app.agents import prompts

    p = prompts.directed_discovery_prompt(
        domain=DOMAIN, capability={"slug": CAP, "name": "Cobrança"}, file="a.go",
        content="x", start_line=1, end_line=1, total_lines=1, max_candidates=5,
        existing=[{"atom_id": "EMB.X.RULE.0001", "title": "Juros", "statement": "1% ao dia",
                   "status": "CANDIDATE"}],
    )
    assert "EMB.X.RULE.0001" in p and "reinforcements" in p and "NÃO crie candidate" in p
    assert "reinforcements" in prompts.DIRECTED_SCHEMA["required"]
