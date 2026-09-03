"""Inventário de fontes + discovery dirigido (um turno por arquivo × capability) em modo
inplace (sem clone), com harness FALSO."""

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

FAKE = [sys.executable, str(Path(__file__).parent / "fake_claude.py")]
DOMAIN = "inv"
CAP = "inv-cobranca"  # slug de capability é chave global: não colidir com outros módulos


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "legado"
    (r / "util").mkdir(parents=True)
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
    (r / "util" / "log.go").write_text("package util\nfunc Log(s string) {}\n", encoding="utf-8")
    (r / "grande.go").write_text(
        "package big\n" + "\n".join(f"// linha {i}" for i in range(2, 2501)) + "\n",
        encoding="utf-8",
    )
    (r / "form.dfm").write_text("object Form1: TForm1\nend\n", encoding="utf-8")  # não é fonte
    (r / "build.dcu").write_bytes(b"\x00\x01")  # binário
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r


@pytest.fixture()
def fonte(client, repo):
    from app.db import SessionLocal
    from app.models.auth import Capability, Domain
    from app.models.knowledge import Source

    with SessionLocal() as db:
        if db.get(Domain, DOMAIN) is None:
            db.add(Domain(slug=DOMAIN, name="Inventário"))
            db.flush()
        if db.get(Capability, CAP) is None:
            db.add(Capability(slug=CAP, domain_slug=DOMAIN, name="Faturamento",
                              description="Emissão de boletos, juros e cobrança"))
        src = Source(type="source_code", name=f"inv-{uuid.uuid4().hex[:6]}",
                     repository=str(repo), created_by="teste")
        db.add(src)
        db.commit()
        return src.id


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "discovery_workspace_mode", "inplace")
    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path / "logs"))
    monkeypatch.setattr(settings, "discovery_chunk_lines", 1000)
    monkeypatch.setenv("FAKE_CAP", CAP)


# ---------- workspace inplace ----------


def test_inplace_nao_copia_e_detecta_escrita(repo):
    from app.engines import workspace

    ws = workspace.open_inplace(str(repo))
    assert ws.inplace and ws.path == repo and ws.root is None
    assert workspace.is_clean(ws)
    (repo / "escrito_pelo_agente.txt").write_text("x", encoding="utf-8")
    assert not workspace.is_clean(ws)  # algo mudou DURANTE o run
    workspace.destroy(ws)  # no-op: o repositório continua lá
    assert repo.exists()


def test_list_files_filtra_extensoes_e_prefixo(repo):
    from app.engines import workspace
    from app.services.inventory import source_extensions

    ws = workspace.open_inplace(str(repo))
    todos = workspace.list_files(ws, source_extensions())
    assert todos == ["billing.go", "billing_test.go", "grande.go", "util/log.go"]
    assert workspace.list_files(ws, source_extensions(), prefix="util/") == ["util/log.go"]


def test_prompts_carregam_contexto_e_linguagem():
    from app.agents import prompts

    p = prompts.code_discovery_prompt(
        "tudo", 10, domain="finance",
        capability={"slug": "caixa", "name": "Caixa", "description": "sangria e fechamento"},
        languages=prompts.language_notes(["a.pas", "b.java", "c.dcu"]),
    )
    assert "Domain: **finance**" in p and "Caixa" in p and "sangria" in p
    assert "Delphi/Object Pascal" in p and "DUnit" in p and "Java" in p
    assert prompts.language_of("x.pas") == "Delphi/Object Pascal"


# ---------- inventário ----------


def test_plan_inventory_lotes_por_tamanho(fonte):
    from app.db import SessionLocal
    from app.models.knowledge import Source
    from app.services.inventory import plan_inventory

    with SessionLocal() as db:
        src = db.get(Source, fonte)
        lotes, total = plan_inventory(db, src, batch_chars=1500)
        assert total == 4
        assert len(lotes) >= 2 and sorted(sum(lotes, [])) == [
            "billing.go", "billing_test.go", "grande.go", "util/log.go"
        ]
        lotes1, _ = plan_inventory(db, src, max_files=2)
        assert lotes1 == [["billing.go", "billing_test.go"]]


def test_inventario_ingere_e_liga_capabilities(fonte, monkeypatch):
    from app.db import SessionLocal
    from app.models.knowledge import Source
    from app.services.inventory import (
        files_for_capability,
        inventory_summary,
        list_inventory,
        plan_inventory,
        run_inventory_batch,
    )

    monkeypatch.setenv("FAKE_SCENARIO", "inventory_ok")
    with SessionLocal() as db:
        src = db.get(Source, fonte)
        lotes, _ = plan_inventory(db, src)
        assert len(lotes) == 1
        run = run_inventory_batch(
            db, source_id=fonte, domain=DOMAIN, files=lotes[0], actor="teste",
            batch_id=uuid.uuid4(), executable=FAKE,
        )
        assert run.status == "succeeded", run.error
        assert run.agent == "inventory" and run.workspace_clean == "yes"
        assert run.candidates_created == 4  # 4 arquivos classificados
        assert run.candidates_rejected == 1  # "fantasma.go" não estava no lote
        assert run.questions_created == 1  # sugestão de capability

        inv = {f["path"]: f for f in list_inventory(db, fonte)}
        assert set(inv) == {"billing.go", "billing_test.go", "grande.go", "util/log.go"}
        assert inv["billing.go"]["capabilities"] == [{"slug": CAP, "relevance": 3, "note": None}]
        assert inv["util/log.go"]["capabilities"] == []
        assert inv["billing.go"]["language"] == "Go" and inv["grande.go"]["lines"] == 2500
        # slug inexistente é descartado
        assert [c["slug"] for c in inv["billing_test.go"]["capabilities"]] == [CAP]

        s = inventory_summary(db, fonte)
        assert s["files"] == 4 and s["files_with_capability"] == 3
        assert s["capabilities"][0]["slug"] == CAP and s["capabilities"][0]["files"] == 3
        assert s["suggestions"][0]["name"] == "Cobrança de Juros"

        assert [sf.path for sf, _ in files_for_capability(db, fonte, CAP, 2)] == [
            "billing.go", "billing_test.go", "grande.go"
        ]
        # only_missing: nada sobra para inventariar
        lotes2, total2 = plan_inventory(db, src)
        assert lotes2 == [] and total2 == 0

        # rodar de novo (--all) acumula hits da sugestão em vez de duplicar
        run2 = run_inventory_batch(
            db, source_id=fonte, domain=DOMAIN, files=lotes[0], actor="teste", executable=FAKE,
        )
        assert run2.status == "succeeded"
        s2 = inventory_summary(db, fonte)
        assert len(s2["suggestions"]) == 1 and s2["suggestions"][0]["hits"] == 2


def test_inventario_exige_capabilities_no_domain(fonte):
    from app.db import SessionLocal
    from app.kernel.errors import KernelError
    from app.models.auth import Domain
    from app.services.inventory import run_inventory_batch

    with SessionLocal() as db:
        if db.get(Domain, "vazio") is None:
            db.add(Domain(slug="vazio", name="Vazio"))
            db.commit()
        with pytest.raises(KernelError, match="não tem capabilities"):
            run_inventory_batch(db, source_id=fonte, domain="vazio", files=["billing.go"],
                                actor="t", executable=FAKE)


# ---------- discovery dirigido ----------


def _inventariar(fonte, monkeypatch):
    from app.db import SessionLocal
    from app.models.knowledge import Source
    from app.services.inventory import plan_inventory, run_inventory_batch

    monkeypatch.setenv("FAKE_SCENARIO", "inventory_ok")
    with SessionLocal() as db:
        src = db.get(Source, fonte)
        lotes, _ = plan_inventory(db, src)
        run_inventory_batch(db, source_id=fonte, domain=DOMAIN, files=lotes[0], actor="t",
                            executable=FAKE)


def test_plan_directed_fatia_arquivos_grandes(fonte, monkeypatch):
    from app.db import SessionLocal
    from app.models.knowledge import Source
    from app.services.discovery import plan_directed

    _inventariar(fonte, monkeypatch)
    with SessionLocal() as db:
        src = db.get(Source, fonte)
        plano = plan_directed(db, src, capability=CAP, min_relevance=2)
        por_arquivo = {}
        for t in plano:
            por_arquivo.setdefault(t["file"], []).append((t["start_line"], t["end_line"]))
        assert por_arquivo["billing.go"] == [(1, 6)]
        assert por_arquivo["grande.go"] == [(1, 1000), (1001, 2000), (2001, 2500)]
        assert plan_directed(db, src, capability=CAP, max_files=1)[0]["file"] == "billing.go"
        assert plan_directed(db, src, capability="outra") == []


def test_run_dirigido_cria_candidates_da_capability_e_followups(fonte, monkeypatch):
    from app.db import SessionLocal
    from app.models.discovery import DiscoveryRun
    from app.models.knowledge import KnowledgeAtom
    from app.services.discovery import run_directed_discovery

    _inventariar(fonte, monkeypatch)
    monkeypatch.setenv("FAKE_SCENARIO", "directed_ok")
    batch = uuid.uuid4()
    with SessionLocal() as db:
        run = run_directed_discovery(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, file="billing.go",
            actor="teste", batch_id=batch, executable=FAKE,
        )
        assert run.status == "succeeded", run.error
        assert run.target_file == "billing.go" and run.line_range == "1-6"
        assert run.batch_id == batch and run.candidates_created == 1
        assert run.workspace_clean == "yes"
        # follow-ups: só arquivos existentes e diferentes do alvo, já fatiados
        assert [f["file"] for f in run.followups] == ["billing_test.go"]
        assert run.followups[0]["start_line"] == 1 and run.followups[0]["end_line"] == 4

        atom = db.scalar(
            select(KnowledgeAtom).where(KnowledgeAtom.title == "Regra dirigida em billing.go")
        )
        assert atom is not None and atom.capability == CAP and atom.domain == DOMAIN

        # idempotência: mesmo arquivo/faixa/commit já sucedido → devolve o run existente
        run2 = run_directed_discovery(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, file="billing.go",
            actor="teste", batch_id=uuid.uuid4(), executable=FAKE,
        )
        assert run2.id == run.id and run2.followups == []

        # faixa de um arquivo grande + marcação de follow-up
        monkeypatch.setenv("FAKE_LINES", "1002-1003")
        run3 = run_directed_discovery(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, file="grande.go",
            start_line=1001, end_line=2000, actor="teste", batch_id=batch, is_followup=True,
            executable=FAKE,
        )
        assert run3.status == "succeeded", run3.error
        assert run3.line_range == "f:1001-2000" and run3.candidates_created == 1
        assert db.get(DiscoveryRun, run3.id).batch_id == batch


def test_run_dirigido_arquivo_ilegivel_vira_failed(fonte):
    from app.db import SessionLocal
    from app.services.discovery import run_directed_discovery

    with SessionLocal() as db:
        run = run_directed_discovery(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, file="../fora.go",
            actor="teste", executable=FAKE,
        )
        assert run.status == "failed" and "ilegível" in (run.error or "")


# ---------- API ----------


def _login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    from app.create_admin import ensure_admin

    ensure_admin("inv-admin@example.com", "Inv", "inv-s3nha-teste")
    return _login(client, "inv-admin@example.com", "inv-s3nha-teste")


class _FakeTask:
    def __init__(self):
        self.calls = []

    def defer(self, **kw):
        self.calls.append(kw)
        return len(self.calls)


def test_api_inventario_e_campanha_enfileiram(client, admin, fonte, monkeypatch):
    import app.discovery.router as router_mod

    fake_plan, fake_dir = _FakeTask(), _FakeTask()
    monkeypatch.setattr(router_mod, "plan_inventory_job", fake_plan)
    monkeypatch.setattr(router_mod, "run_directed_job", fake_dir)

    # capability description editável
    r = client.patch(f"/admin/capabilities/{CAP}", json={"description": "boletos e juros"},
                     headers=admin)
    assert r.status_code == 200 and r.json()["description"] == "boletos e juros"

    # a API só enfileira o PLANEJAMENTO (o container não vê o repositório do host)
    r = client.post("/discovery/inventory", json={
        "source_id": str(fonte), "domain": DOMAIN, "prefix": "util/"}, headers=admin)
    assert r.status_code == 202, r.text
    assert r.json()["planning"] is True and len(fake_plan.calls) == 1
    assert fake_plan.calls[0]["batch_id"] == r.json()["batch_id"]
    assert fake_plan.calls[0]["prefix"] == "util/"

    # o planejamento no host gera um run_inventory_job por lote
    from app.db import SessionLocal
    from app.jobs import inventory_batch_kwargs

    with SessionLocal() as db:
        lotes = inventory_batch_kwargs(
            db, source_id=str(fonte), domain=DOMAIN, prefix=None, max_files=None,
            only_missing=True, actor="t", batch_id="b1", budget_usd=2.0,
        )
    assert len(lotes) == 1 and sorted(lotes[0]["files"]) == [
        "billing.go", "billing_test.go", "grande.go", "util/log.go"
    ]
    assert lotes[0]["batch_id"] == "b1" and lotes[0]["budget_usd"] == 2.0

    # campanha sem inventário → erro claro
    r = client.post("/discovery/campaigns", json={
        "source_id": str(fonte), "domain": DOMAIN, "capability": CAP}, headers=admin)
    assert r.status_code == 400 and "inventário" in r.json()["detail"]

    _inventariar(fonte, monkeypatch)
    r = client.post("/discovery/campaigns", json={
        "source_id": str(fonte), "domain": DOMAIN, "capability": CAP, "budget_usd": 2},
        headers=admin)
    assert r.status_code == 202, r.text
    assert r.json()["files"] == 3 and r.json()["jobs"] == 5 == len(fake_dir.calls)
    assert {c["file"] for c in fake_dir.calls} == {"billing.go", "billing_test.go", "grande.go"}

    s = client.get(f"/sources/{fonte}/inventory/summary", headers=admin).json()
    assert s["files"] == 4 and s["capabilities"][0]["slug"] == CAP
    arquivos = client.get(f"/sources/{fonte}/inventory?capability={CAP}", headers=admin).json()
    assert len(arquivos) == 3

    # batches: aparece a campanha inventariada (runs) mesmo sem schema do procrastinate
    r = client.get("/discovery/batches", headers=admin)
    assert r.status_code == 200
    assert any(b["agent"] == "inventory" and b["succeeded"] >= 1 for b in r.json())
