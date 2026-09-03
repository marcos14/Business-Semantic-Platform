"""Workspace apontando para SUBDIRETÓRIO do repositório git + falha de clone auditável.

Caso real: a Source registra `<repo>/source` enquanto o `.git` está em `<repo>`.
"""

import subprocess
import uuid

import pytest


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo_com_subdir(tmp_path):
    repo = tmp_path / "erp"
    (repo / "source" / "mod").mkdir(parents=True)
    (repo / "dist").mkdir()
    (repo / "source" / "mod" / "Caixa.pas").write_text(
        "unit Caixa;\n"
        "// Sangria acima de 500 exige supervisor\n"
        "function PodeSangrar(valor: Currency): Boolean;\n"
        "begin\n"
        "  Result := valor <= 500;\n"
        "end;\n",
        encoding="utf-8",
    )
    (repo / "dist" / "erp.exe").write_bytes(b"\x00binario")
    (repo / "README.md").write_text("raiz\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_subdiretorio_clona_raiz_e_aponta_para_o_subdir(repo_com_subdir):
    from app.engines import workspace

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_com_subdir, capture_output=True, text=True
    ).stdout.strip()

    ws = workspace.create(str(repo_com_subdir / "source"))
    try:
        assert ws.commit == head
        assert ws.subdir == "source"
        assert ws.path.name == "source" and ws.path.is_dir()
        assert ws.root is not None and ws.root.exists()
        # citações relativas ao subdiretório funcionam; traversal para fora não
        trecho = workspace.read_lines(ws, "mod/Caixa.pas", 2, 3)
        assert trecho is not None and "Sangria" in trecho
        assert workspace.read_lines(ws, "../README.md", 1, 1) is None
        # sparse-checkout: o resto do repo não é materializado
        assert not (ws.path.parent / "dist").exists()
        assert workspace.is_clean(ws)
    finally:
        workspace.destroy(ws)
    assert not ws.root.exists()


def test_raiz_do_repo_continua_funcionando(repo_com_subdir):
    from app.engines import workspace

    ws = workspace.create(str(repo_com_subdir))
    try:
        assert ws.subdir is None
        assert (ws.path / "dist" / "erp.exe").exists()
        assert (ws.path / "source" / "mod" / "Caixa.pas").exists()
    finally:
        workspace.destroy(ws)


def test_subdiretorio_inexistente_no_commit(repo_com_subdir):
    from app.engines import workspace

    (repo_com_subdir / "novo").mkdir()  # existe no disco, mas não no commit
    with pytest.raises(RuntimeError, match="não existe no commit"):
        workspace.create(str(repo_com_subdir / "novo"))


def test_caminho_sem_git_da_erro_claro(tmp_path):
    from app.engines import workspace

    solto = tmp_path / "solto"
    solto.mkdir()
    with pytest.raises(RuntimeError, match="Repositório git não encontrado"):
        workspace.create(str(solto))
    with pytest.raises(RuntimeError, match="Diretório não encontrado"):
        workspace.create(str(tmp_path / "nao-existe"))


def test_falha_de_clone_vira_run_failed(client, tmp_path):
    """A falha aparece em /discovery/runs (tela) em vez de morrer só no log do worker."""
    from app.db import SessionLocal
    from app.models.discovery import DiscoveryRun
    from app.models.knowledge import Source
    from app.services.discovery import run_discovery

    solto = tmp_path / "sem-git"
    solto.mkdir()
    with SessionLocal() as db:
        src = Source(
            type="source_code", name=f"quebrada-{uuid.uuid4().hex[:6]}",
            repository=str(solto), created_by="teste",
        )
        db.add(src)
        db.commit()
        run = run_discovery(
            db, source_id=src.id, agent="code", domain="qualquer", capability=None,
            actor="teste",
        )
        assert run.status == "failed"
        assert run.commit is None
        assert "Repositório git não encontrado" in (run.error or "")
        assert run.finished_at is not None
        assert db.get(DiscoveryRun, run.id) is not None
