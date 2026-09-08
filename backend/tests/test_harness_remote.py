"""Executor remoto (HARNESS_EXECUTOR=remote): o worker publica a chamada ao harness como
tarefa, um agente na máquina de um membro da equipe executa com a própria chave e o
servidor ingere o resultado. O executor local continua sendo o padrão e não muda.

O "agente" aqui é o próprio teste, falando com a API como o `bsp-agent` fala, e rodando
o harness FALSO (fake_claude.py) exatamente como o agente real roda o `claude`.
"""

import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

FAKE = [sys.executable, str(Path(__file__).parent / "fake_claude.py")]
HELLO = {
    "agent_version": "0.1.0", "cli_version": "9.9.9 (fake)", "host": "laptop-a", "state": "idle",
}


def _login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin(client):
    from app.create_admin import ensure_admin

    ensure_admin("harness-admin@example.com", "Harness", "harness-s3nha-teste")
    return _login(client, "harness-admin@example.com", "harness-s3nha-teste")


def _novo_agente(client, admin, nome: str) -> dict:
    email = f"dev-{uuid.uuid4().hex[:6]}@example.com"
    u = client.post(
        "/admin/users", json={"email": email, "name": nome, "password": "senha-forte-123"},
        headers=admin,
    )
    assert u.status_code == 201, u.text
    a = client.post(
        "/harness/agents", json={"name": nome, "user_id": u.json()["id"]}, headers=admin
    )
    assert a.status_code == 201, a.text
    d = a.json()
    return {
        "id": d["id"], "email": email, "name": nome,
        "headers": {"X-BSP-Agent-Key": d["api_key"]},
    }


def _agente_listado(client, admin, agent_id: str) -> dict:
    agentes = client.get("/harness/agents", headers=admin).json()
    return next(a for a in agentes if a["id"] == agent_id)


@pytest.fixture(scope="module")
def agente_a(client, admin):
    return _novo_agente(client, admin, "Laptop A")


@pytest.fixture(scope="module")
def agente_b(client, admin):
    return _novo_agente(client, admin, "Laptop B")


@pytest.fixture()
def remoto(monkeypatch, tmp_path):
    """Liga o executor remoto só durante o teste, com espera curta."""
    from app.config import settings

    monkeypatch.setattr(settings, "harness_executor", "remote")
    monkeypatch.setattr(settings, "harness_poll_seconds", 0.1)
    monkeypatch.setattr(settings, "harness_remote_wait_seconds", 60)
    monkeypatch.setattr(settings, "harness_task_lease_seconds", 180)
    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path / "logs"))
    return settings


@pytest.fixture()
def repo_legado(tmp_path):
    repo = tmp_path / "legado"
    repo.mkdir()
    (repo / "billing.go").write_text(
        "package billing\n\n// JurosDiarios calcula juros de boleto vencido\n"
        "func JurosDiarios(valor float64, dias int) float64 {\n"
        "\treturn valor * 0.01 * float64(dias)\n}\n",
        encoding="utf-8",
    )
    (repo / "billing_test.go").write_text(
        "package billing\n\nfunc TestJuros(t *testing.T) {\n\t// 1% ao dia\n}\n",
        encoding="utf-8",
    )
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(cmd, cwd=repo, check=True)
    return repo


@pytest.fixture()
def fonte(client, repo_legado):
    from app.db import SessionLocal
    from app.models.auth import Capability, Domain
    from app.models.knowledge import Source

    with SessionLocal() as db:
        if db.get(Domain, "remoto") is None:
            db.add(Domain(slug="remoto", name="Remoto"))
            db.flush()
        if db.get(Capability, "billing-remoto") is None:
            db.add(Capability(slug="billing-remoto", domain_slug="remoto", name="Billing"))
        src = Source(
            type="source_code", name=f"legado-remoto-{uuid.uuid4().hex[:6]}",
            repository=str(repo_legado), git_url=str(repo_legado), created_by="teste",
        )
        db.add(src)
        db.commit()
        return src.id


def _claim(client, agente, tentativas=100, **extra):
    for _ in range(tentativas):
        r = client.post("/harness/agent/claim", json={**HELLO, **extra}, headers=agente["headers"])
        if r.status_code == 200:
            return r.json()
        assert r.status_code == 204, r.text
        time.sleep(0.1)
    return None


# ---------- autenticação e registro ----------


def test_credencial_e_versao(client, admin, agente_a):
    assert client.post("/harness/agent/register", json=HELLO).status_code == 401
    assert client.post(
        "/harness/agent/register", json=HELLO, headers={"X-BSP-Agent-Key": "hag_x.errada"}
    ).status_code == 401
    velho = client.post(
        "/harness/agent/register", json={**HELLO, "agent_version": "0.0.1"},
        headers=agente_a["headers"],
    )
    assert velho.status_code == 426
    ok = client.post("/harness/agent/register", json=HELLO, headers=agente_a["headers"])
    assert ok.status_code == 200, ok.text
    assert ok.json()["name"] == "Laptop A" and ok.json()["protocol"] == 1

    listado = _agente_listado(client, admin, agente_a["id"])
    assert listado["status"] == "idle" and listado["user_email"] == agente_a["email"]
    assert "api_key" not in listado and "secret" not in str(listado)


def test_rotacao_e_revogacao(client, admin):
    ag = _novo_agente(client, admin, "Descartável")
    reg = client.post("/harness/agent/register", json=HELLO, headers=ag["headers"])
    assert reg.status_code == 200
    rot = client.post(f"/harness/agents/{ag['id']}/rotate", headers=admin)
    assert rot.status_code == 200
    nova = {"X-BSP-Agent-Key": rot.json()["api_key"]}
    velha = client.post("/harness/agent/register", json=HELLO, headers=ag["headers"])
    assert velha.status_code == 401
    assert client.post("/harness/agent/register", json=HELLO, headers=nova).status_code == 200
    assert client.delete(f"/harness/agents/{ag['id']}", headers=admin).status_code == 200
    assert client.post("/harness/agent/register", json=HELLO, headers=nova).status_code == 401
    assert client.post(f"/harness/agents/{ag['id']}/rotate").status_code == 401  # sem JWT


# ---------- fluxo completo: worker → tarefa → agente → ingestão ----------


def test_discovery_executado_por_agente_remoto(
    client, admin, agente_a, fonte, repo_legado, remoto, monkeypatch, tmp_path
):
    from app.agent import runner
    from app.db import SessionLocal
    from app.engines import claude_code
    from app.services.discovery import run_discovery

    saida: dict = {}

    def worker():
        with SessionLocal() as db:
            saida["run"] = run_discovery(
                db, source_id=fonte, agent="code", domain="remoto",
                capability="billing-remoto", actor="teste", timeout_min=2,
            )

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        task = _claim(client, agente_a)
        assert task, "o worker não publicou a tarefa"
        pacote = task["packet"]
        assert pacote["protocol"] == 1 and pacote["prompt"] and pacote["schema"]
        assert pacote["source"]["id"] == str(fonte)
        assert pacote["source"]["git_url"] == str(repo_legado)
        assert len(pacote["source"]["commit"]) == 40
        assert pacote["tools"] == ["Read", "Grep", "Glob"]  # inplace: só leitura
        assert task["attempt"] == 1

        hb = client.post(
            f"/harness/agent/tasks/{task['task_id']}/heartbeat", headers=agente_a["headers"]
        )
        assert hb.status_code == 200 and hb.json()["status"] == "leased"
        # outro agente não consegue mexer na tarefa arrendada
        assert client.post(
            f"/harness/agent/tasks/{task['task_id']}/heartbeat",
            headers=_novo_agente(client, admin, "Intruso")["headers"],
        ).status_code == 409

        # o agente executa com o harness falso, no clone (aqui: o próprio repo, mesmo commit)
        monkeypatch.setenv("FAKE_SCENARIO", "discovery_ok")
        res = runner.execute(pacote, repo_legado, tmp_path / "agent-logs", executable=FAKE)
        res.workspace_clean = True
        log = Path(res.log_path).read_text(encoding="utf-8")
        r = client.post(
            f"/harness/agent/tasks/{task['task_id']}/result",
            json={"result": claude_code.result_to_dict(res), "log_text": log},
            headers=agente_a["headers"],
        )
        assert r.status_code == 200, r.text
        assert r.json()["outcome"] == "done"
    finally:
        t.join(timeout=30)
    assert not t.is_alive(), "o broker não voltou depois do resultado"

    run = saida["run"]
    assert run.status == "succeeded", run.error
    assert run.candidates_created == 2 and run.questions_created == 1
    assert run.cost_usd == 0.42
    assert run.executed_by == f"Laptop A <{agente_a['email']}>"
    assert run.workspace_clean == "yes"
    assert run.cli_version == "9.9.9 (Claude Code fake)"
    # o log do agente foi persistido no diretório de logs do worker (auditoria §87)
    assert run.log_path.startswith(str(tmp_path / "logs")) and Path(run.log_path).exists()
    assert '"type": "result"' in Path(run.log_path).read_text(encoding="utf-8")

    api_run = client.get(f"/discovery/runs/{run.id}", headers=admin).json()
    assert api_run["executed_by"] == run.executed_by

    ag = _agente_listado(client, admin, agente_a["id"])
    assert ag["tasks_done"] >= 1 and ag["cost_usd_today"] >= 0.42
    tarefas = client.get("/harness/tasks?status=succeeded", headers=admin).json()
    assert any(x["id"] == task["task_id"] and x["run_id"] == str(run.id) for x in tarefas)


def test_limite_no_agente_devolve_tarefa_e_afasta_o_agente(
    client, admin, agente_a, agente_b, remoto, tmp_path
):
    from app.db import SessionLocal
    from app.engines import claude_code
    from app.harness import service

    with SessionLocal() as db:
        task_id = str(service.create_task(db, claude_code.RunOptions(
            workdir=tmp_path, prompt="p", logs_dir=tmp_path, label="limite",
        )).id)

    task = _claim(client, agente_a, tentativas=3)
    assert task and task["task_id"] == task_id
    resultado = {
        "is_error": True, "subtype": "limite de sessão/uso", "result_text": "session limit",
        "session_limit": True,
        "limit_detail": "You've hit your session limit · resets 10:30pm (America/Sao_Paulo)",
        "cost_usd": 0.0, "num_turns": 0, "cli_version": "9.9.9 (fake)",
    }
    r = client.post(
        f"/harness/agent/tasks/{task_id}/result", json={"result": resultado},
        headers=agente_a["headers"],
    )
    assert r.status_code == 200 and r.json()["outcome"] == "requeued", r.text

    ag = _agente_listado(client, admin, agente_a["id"])
    assert ag["status"] == "limited" and ag["limited_until"]
    # A não recebe nada enquanto limitado; B pega a MESMA tarefa na tentativa 2
    nada = client.post("/harness/agent/claim", json=HELLO, headers=agente_a["headers"])
    assert nada.status_code == 204
    t2 = _claim(client, agente_b, tentativas=3)
    assert t2 and t2["task_id"] == task_id and t2["attempt"] == 2

    st = client.get("/harness/status", headers=admin).json()
    assert st["executor"] == "remote" and st["tasks"].get("leased", 0) >= 1

    with SessionLocal() as db:
        service.cancel_task(db, db.get(service.HarnessTask, uuid.UUID(task_id)), "fim do teste")
        # libera o agente A para os próximos testes
        a = db.get(service.HarnessAgent, uuid.UUID(agente_a["id"]))
        a.limited_until = None
        db.commit()


def test_lease_vencido_volta_para_a_fila(
    client, admin, agente_a, agente_b, remoto, monkeypatch, tmp_path
):
    from app.db import SessionLocal
    from app.engines import claude_code
    from app.harness import service

    monkeypatch.setattr(remoto, "harness_task_lease_seconds", 0)
    with SessionLocal() as db:
        task_id = str(service.create_task(db, claude_code.RunOptions(
            workdir=tmp_path, prompt="p", logs_dir=tmp_path, label="lease",
        )).id)
    t1 = _claim(client, agente_a, tentativas=3)
    assert t1 and t1["task_id"] == task_id
    time.sleep(0.05)
    t2 = _claim(client, agente_b, tentativas=3)  # o claim de B varre o lease vencido de A
    assert t2 and t2["task_id"] == task_id and t2["attempt"] == 2
    # A perdeu a tarefa: heartbeat e resultado são recusados
    hb = client.post(f"/harness/agent/tasks/{task_id}/heartbeat", headers=agente_a["headers"])
    assert hb.status_code == 409
    assert client.post(
        f"/harness/agent/tasks/{task_id}/result", json={"result": {"is_error": False}},
        headers=agente_a["headers"],
    ).status_code == 409
    # falha declarada por B (ex.: clone impossível) devolve à fila; na 3ª tentativa esgota
    monkeypatch.setattr(remoto, "harness_task_lease_seconds", 180)
    r = client.post(
        f"/harness/agent/tasks/{task_id}/fail",
        json={"kind": "workspace", "detail": "commit ausente"},
        headers=agente_b["headers"],
    )
    assert r.status_code == 200 and r.json()["status"] == "ready"
    t3 = _claim(client, agente_b, tentativas=3)
    assert t3 and t3["attempt"] == 3
    r = client.post(
        f"/harness/agent/tasks/{task_id}/fail",
        json={"kind": "workspace", "detail": "commit ausente"},
        headers=agente_b["headers"],
    )
    assert r.json()["status"] == "failed"
    detalhe = client.get(f"/harness/tasks/{task_id}", headers=admin).json()
    assert "tentativas esgotadas" in detalhe["error"] and detalhe["packet"]["prompt"] == "p"


def test_sem_agente_o_run_falha_no_prazo(remoto, monkeypatch, tmp_path):
    from app.db import SessionLocal
    from app.engines import claude_code
    from app.harness import service

    monkeypatch.setattr(remoto, "harness_remote_wait_seconds", 1)
    res = claude_code.run(claude_code.RunOptions(
        workdir=tmp_path, prompt="ninguém vai pegar", logs_dir=tmp_path / "logs", label="orfa",
    ))
    assert res.is_error and res.subtype == "executor remoto"
    assert "prazo" in res.result_text
    with SessionLocal() as db:
        canceladas = [t for t in db.query(service.HarnessTask).filter_by(label="orfa")]
        assert canceladas and all(t.status == "cancelled" for t in canceladas)


def test_executor_local_continua_sendo_o_padrao(tmp_path, monkeypatch):
    from app.config import settings
    from app.engines import claude_code

    assert settings.harness_executor == "local"
    monkeypatch.setenv("FAKE_SCENARIO", "discovery_ok")
    res = claude_code.run(claude_code.RunOptions(
        workdir=tmp_path, prompt="x", logs_dir=tmp_path / "logs", label="local", executable=FAKE,
        timeout_min=1,
    ))
    assert not res.is_error and res.executed_by is None and res.duration_ms is not None


# ---------- lado do agente: clone em cache e utilitários ----------


def test_agente_clona_em_cache_no_commit_fixado(repo_legado, tmp_path, monkeypatch):
    from app.agent import config as cfgmod
    from app.agent import workspace as aws

    monkeypatch.setenv("BSP_AGENT_HOME", str(tmp_path / "agent-home"))
    cfg = cfgmod.AgentConfig(cache_dir=str(tmp_path / "cache"))
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_legado, capture_output=True, text=True, check=True
    ).stdout.strip()
    source = {"id": "src-1", "git_url": str(repo_legado), "subdir": None, "commit": commit}

    cwd, raiz = aws.ensure_checkout(cfg, source)
    assert cwd == raiz and (cwd / "billing.go").exists()
    assert aws.head_commit(raiz) == commit
    antes = aws.status_snapshot(raiz)
    assert aws.is_clean(raiz, antes)
    (raiz / "sujo.txt").write_text("x", encoding="utf-8")
    assert not aws.is_clean(raiz, antes)

    # segundo run: reaproveita o clone e volta ao commit limpo
    cwd2, _ = aws.ensure_checkout(cfg, source)
    assert cwd2 == cwd and not (raiz / "sujo.txt").exists()

    # commit inexistente → erro claro (a tarefa volta para a fila)
    with pytest.raises(aws.WorkspaceError):
        aws.ensure_checkout(cfg, {**source, "commit": "0" * 40})
    # sem origem alcançável → orienta a configurar o caminho local
    with pytest.raises(aws.WorkspaceError, match="setup --source"):
        aws.ensure_checkout(cfg, {"id": "src-2", "commit": commit})
    # caminho local configurado serve de origem
    cfg.sources["src-2"] = {"path": str(repo_legado)}
    cwd3, _ = aws.ensure_checkout(cfg, {"id": "src-2", "commit": commit})
    assert (cwd3 / "billing.go").exists()


def test_config_e_janelas_do_agente(tmp_path, monkeypatch):
    from datetime import datetime

    from app.agent import config as cfgmod

    monkeypatch.setenv("BSP_AGENT_HOME", str(tmp_path / "home"))
    cfg = cfgmod.AgentConfig(api_url="http://x/", api_key="hag_a.b", active_hours=["18:30-08:00"])
    cfgmod.save(cfg)
    lido = cfgmod.load()
    assert lido.api_key == "hag_a.b" and lido.active_hours == ["18:30-08:00"]
    assert cfgmod.within_hours(["18:30-08:00"], datetime(2026, 9, 7, 23, 0))
    assert cfgmod.within_hours(["18:30-08:00"], datetime(2026, 9, 7, 7, 59))
    assert not cfgmod.within_hours(["18:30-08:00"], datetime(2026, 9, 7, 12, 0))
    assert cfgmod.within_hours(["12:00-13:30"], datetime(2026, 9, 7, 12, 30))
    assert cfgmod.within_hours([], datetime(2026, 9, 7, 3, 0))
    st = cfgmod.load_state()
    st.paused = True
    st.usd_today = 1.5
    cfgmod.save_state(st)
    assert cfgmod.load_state().paused and cfgmod.load_state().usd_today == 1.5
