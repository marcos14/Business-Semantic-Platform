"""CLI do agente remoto.

  bsp-agent setup --api https://bsp.exemplo --key hag_xxx.yyy --name "Laptop da Ana"
  bsp-agent run [--once] [--max-usd-per-day 15] [--hours 12:00-13:30,18:30-08:00]
  bsp-agent status | pause | resume | doctor

Sem `bsp-agent` instalado: `uv run python -m app.agent.cli ...` dentro de backend/.
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from app.agent import AGENT_VERSION, runner, workspace
from app.agent import config as cfgmod
from app.agent.client import AgentApiError, AgentClient, UpgradeRequired
from app.engines import claude_code


def _log(msg: str) -> None:
    print(f"[bsp-agent {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _hello(cfg: cfgmod.AgentConfig, state: str) -> dict:
    return {
        "agent_version": AGENT_VERSION,
        "cli_version": claude_code.cli_version(cfg.claude_executable),
        "host": socket.gethostname()[:200],
        "state": state,
        "sources": None,
    }


def _sleep(segundos: float) -> None:
    time.sleep(max(0.0, segundos))


# ---------- heartbeat ----------


class Heartbeat(threading.Thread):
    def __init__(self, client: AgentClient, task_id: str, interval: int):
        super().__init__(daemon=True)
        self._client, self._task_id, self._interval = client, task_id, max(5, interval)
        self._stop = threading.Event()
        self.cancelled = False

    def run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                r = self._client.heartbeat(self._task_id)
                if r.get("status") not in ("leased",):
                    self.cancelled = True
                    _log(f"tarefa {self._task_id[:8]} não está mais arrendada ({r.get('status')})")
            except Exception as e:  # rede instável não derruba o run
                _log(f"heartbeat falhou: {e}")

    def stop(self) -> None:
        self._stop.set()


# ---------- execução de uma tarefa ----------


def _read_log(path: str | None, max_chars: int) -> str | None:
    if not path:
        return None
    try:
        texto = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return texto[-max_chars:] if len(texto) > max_chars else texto


def execute_task(
    cfg: cfgmod.AgentConfig, client: AgentClient, task: dict, *, log_max_chars: int
) -> str:
    task_id = task["task_id"]
    packet = task.get("packet") or {}
    label = packet.get("label") or task_id[:8]
    _log(f"tarefa {task_id[:8]} ({label}), tentativa {task.get('attempt')}: iniciando")
    hb = Heartbeat(client, task_id, int(task.get("heartbeat_seconds") or 60))
    hb.start()
    try:
        source = packet.get("source")
        repo: Path | None = None
        antes: frozenset[str] = frozenset()
        if source:
            try:
                workdir, repo = workspace.ensure_checkout(cfg, source)
            except workspace.WorkspaceError as e:
                _log(f"workspace indisponível: {e}")
                client.fail(task_id, "workspace", str(e))
                return "workspace"
            antes = workspace.status_snapshot(repo)
        else:
            workdir = cfg.logs_dir
            workdir.mkdir(parents=True, exist_ok=True)

        res = runner.execute(packet, workdir, cfg.logs_dir, executable=cfg.claude_executable)
        if repo is not None:
            res.workspace_clean = workspace.is_clean(repo, antes)

        texto = f"{res.result_text}\n{res.stderr_tail}"
        if (
            res.is_error and not res.session_limit and not res.auth_failed
            and claude_code.is_rate_limited(texto)
        ):
            _log("rate limit da API; devolvendo a tarefa e esperando 60s")
            client.fail(task_id, "rate_limit", res.result_text[:500])
            _sleep(60)
            return "rate_limit"

        log_text = _read_log(res.log_path, log_max_chars)
        r = client.result(task_id, claude_code.result_to_dict(res), log_text)
        st = cfgmod.load_state()
        st.usd_today += float(res.cost_usd or 0.0)
        st.tasks_today += 1
        cfgmod.save_state(st)
        _log(
            f"tarefa {task_id[:8]}: {'erro ' + str(res.subtype) if res.is_error else 'ok'} · "
            f"US$ {res.cost_usd:.2f} · {res.num_turns} turno(s) · servidor: {r.get('outcome')}"
        )
        if r.get("outcome") in ("done", "requeued", "ignored") and res.log_path:
            try:
                Path(res.log_path).unlink()  # o log já está no servidor
            except OSError:
                pass
        if res.session_limit:
            segundos = claude_code.delay_until_reset(res.limit_detail)
            _log(f"limite de franquia nesta conta; pausando por {segundos // 60}min")
            _sleep(segundos)
        elif res.auth_failed:
            _log(
                "harness deslogado ou chave inválida: verifique ANTHROPIC_API_KEY ou "
                "`claude /login`; pausando 5min"
            )
            _sleep(300)
        return "done"
    except Exception as e:  # noqa: BLE001 — qualquer falha devolve a tarefa
        _log(f"exceção ao executar: {e!r}")
        try:
            client.fail(task_id, "exception", repr(e))
        except Exception:
            pass
        return "exception"
    finally:
        hb.stop()


# ---------- comandos ----------


def cmd_run(cfg: cfgmod.AgentConfig, args) -> int:
    if not cfg.api_key:
        print("Sem credencial. Rode `bsp-agent setup --api ... --key ...` primeiro.")
        return 2
    if args.max_usd_per_day is not None:
        cfg.max_usd_per_day = args.max_usd_per_day
    if args.hours:
        cfg.active_hours = [h.strip() for h in args.hours.split(",") if h.strip()]
    if cfg.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", cfg.anthropic_api_key)
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)

    client = AgentClient(cfg.api_url, cfg.api_key)
    try:
        info = client.register(_hello(cfg, "idle"))
    except UpgradeRequired as e:
        print(e.detail)
        return 2
    except (AgentApiError, httpx.HTTPError) as e:
        print(f"Não foi possível registrar em {cfg.api_url}: {e}")
        return 2
    executor = info.get("executor")
    _log(
        f"registrado como '{info.get('name')}' em {cfg.api_url} (executor do servidor: {executor}; "
        f"protocolo {info.get('protocol')})"
    )
    if executor != "remote":
        _log("aviso: o servidor está no executor LOCAL; nenhuma tarefa será publicada até "
             "HARNESS_EXECUTOR=remote no worker.")
    poll = int(info.get("poll_seconds") or cfg.poll_seconds)
    log_max = int(info.get("log_max_chars") or 4_000_000)

    while True:
        st = cfgmod.load_state()
        if st.paused:
            _log("pausado (bsp-agent resume para voltar)")
            try:
                client.claim(_hello(cfg, "paused"))
            except Exception:
                pass
            _sleep(60)
            continue
        if not cfgmod.within_hours(cfg.active_hours):
            _sleep(60)
            continue
        if cfg.max_usd_per_day and st.usd_today >= cfg.max_usd_per_day:
            _log(
                f"teto diário atingido (US$ {st.usd_today:.2f} ≥ "
                f"{cfg.max_usd_per_day:.2f}); esperando"
            )
            _sleep(300)
            continue
        try:
            task = client.claim(_hello(cfg, "idle"))
        except UpgradeRequired as e:
            print(e.detail)
            return 2
        except (AgentApiError, httpx.HTTPError) as e:
            _log(f"API indisponível ({e}); tentando de novo em 30s")
            _sleep(30)
            continue
        if task is None:
            if args.once:
                _log("nada a fazer")
                return 0
            _sleep(poll)
            continue
        execute_task(cfg, client, task, log_max_chars=log_max)
        if args.once:
            return 0


def cmd_setup(cfg: cfgmod.AgentConfig, args) -> int:
    if args.api:
        cfg.api_url = args.api.rstrip("/")
    if args.key:
        cfg.api_key = args.key.strip()
    if args.name:
        cfg.name = args.name
    if args.cache_dir:
        cfg.cache_dir = str(Path(args.cache_dir).expanduser())
    if args.claude:
        cfg.claude_executable = args.claude
    if args.anthropic_key is not None:
        cfg.anthropic_api_key = args.anthropic_key
    if args.max_usd_per_day is not None:
        cfg.max_usd_per_day = args.max_usd_per_day
    if args.hours is not None:
        cfg.active_hours = [h.strip() for h in args.hours.split(",") if h.strip()]
    if args.poll:
        cfg.poll_seconds = args.poll
    for item in args.source or []:
        if "=" not in item:
            print(f"--source espera <source_id>=<caminho>: {item}")
            return 2
        sid, caminho = item.split("=", 1)
        cfg.sources[sid.strip()] = {"path": str(Path(caminho.strip()).expanduser())}
    p = cfgmod.save(cfg)
    print(f"Configuração gravada em {p}")
    if cfg.api_key:
        client = AgentClient(cfg.api_url, cfg.api_key)
        try:
            info = client.register(_hello(cfg, "idle"))
            print(
                f"Registrado como '{info.get('name')}' "
                f"(executor do servidor: {info.get('executor')})"
            )
        except (AgentApiError, httpx.HTTPError) as e:
            print(f"Registro falhou: {e}")
            return 1
    return 0


def cmd_status(cfg: cfgmod.AgentConfig, _args) -> int:
    st = cfgmod.load_state()
    print(f"config:   {cfgmod.config_path()}")
    print(f"api:      {cfg.api_url}")
    print(f"nome:     {cfg.name or '(sem nome)'}")
    print(f"cache:    {cfg.repos_dir}")
    print(f"claude:   {cfg.claude_executable} ({claude_code.cli_version(cfg.claude_executable)})")
    print(f"horários: {', '.join(cfg.active_hours) or 'sempre'}")
    teto = f"US$ {cfg.max_usd_per_day:.2f}" if cfg.max_usd_per_day else "sem teto"
    print(f"teto/dia: {teto}")
    pausado = " · PAUSADO" if st.paused else ""
    print(f"hoje:     {st.tasks_today} tarefa(s), US$ {st.usd_today:.2f}{pausado}")
    if cfg.api_key:
        try:
            estado = "paused" if st.paused else "idle"
            info = AgentClient(cfg.api_url, cfg.api_key).register(_hello(cfg, estado))
            print(
                f"servidor: '{info.get('name')}' · executor {info.get('executor')} · "
                f"protocolo {info.get('protocol')}"
            )
        except (AgentApiError, httpx.HTTPError) as e:
            print(f"servidor: inacessível ({e})")
    return 0


def cmd_pause(_cfg, _args) -> int:
    st = cfgmod.load_state()
    st.paused = True
    cfgmod.save_state(st)
    print("Pausado: o agente não pega tarefas novas até `bsp-agent resume`.")
    return 0


def cmd_resume(_cfg, _args) -> int:
    st = cfgmod.load_state()
    st.paused = False
    cfgmod.save_state(st)
    print("Retomado.")
    return 0


def cmd_doctor(cfg: cfgmod.AgentConfig, _args) -> int:
    ok = True
    git = shutil.which("git")
    print(f"git:    {git or 'NÃO ENCONTRADO'}")
    ok &= bool(git)
    exe = shutil.which(cfg.claude_executable) or cfg.claude_executable
    versao = claude_code.cli_version(cfg.claude_executable)
    print(f"claude: {exe} ({versao})")
    ok &= versao not in ("indisponível", "desconhecida")
    chave = "ANTHROPIC_API_KEY" in os.environ or bool(cfg.anthropic_api_key)
    chave_txt = (
        "ANTHROPIC_API_KEY presente" if chave else "sem ANTHROPIC_API_KEY (usará o claude logado)"
    )
    print(f"chave:  {chave_txt}")
    try:
        r = httpx.get(cfg.api_url.rstrip("/") + "/health", timeout=10)
        print(f"api:    {cfg.api_url} -> HTTP {r.status_code}")
        ok &= r.status_code < 500
    except httpx.HTTPError as e:
        print(f"api:    {cfg.api_url} inacessível ({e})")
        ok = False
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10)
        print(f"        {out.stdout.strip()}")
    except Exception:
        pass
    print("OK" if ok else "Há pendências acima.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bsp-agent", description=__doc__)
    parser.add_argument("--version", action="version", version=f"bsp-agent {AGENT_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("setup", help="grava a configuração desta máquina e registra na API")
    ps.add_argument("--api", help="URL da API do BSP")
    ps.add_argument("--key", help="credencial do agente (client_id.secret) criada pelo admin")
    ps.add_argument("--name", help="rótulo desta máquina")
    ps.add_argument("--cache-dir", help="onde guardar os clones em cache")
    ps.add_argument("--claude", help="executável do harness (padrão: claude)")
    ps.add_argument("--anthropic-key", help="chave de API exportada só para o harness (opcional)")
    ps.add_argument(
        "--max-usd-per-day", type=float, help="teto diário (estimativa local); 0 = sem teto"
    )
    ps.add_argument(
        "--hours", help='janelas ativas, ex.: "12:00-13:30,18:30-08:00"; vazio = sempre'
    )
    ps.add_argument("--poll", type=int, help="segundos entre consultas à fila")
    ps.add_argument(
        "--source", action="append",
        help="<source_id>=<caminho local do repositório> (repetível)",
    )
    ps.set_defaults(func=cmd_setup)

    pr = sub.add_parser("run", help="consome tarefas até ser interrompido")
    pr.add_argument("--once", action="store_true", help="executa no máximo uma tarefa e sai")
    pr.add_argument("--max-usd-per-day", type=float, default=None)
    pr.add_argument("--hours", default=None)
    pr.set_defaults(func=cmd_run)

    for nome, ajuda, fn in (
        ("status", "configuração, gasto do dia e estado no servidor", cmd_status),
        ("pause", "para de pegar tarefas novas", cmd_pause),
        ("resume", "volta a pegar tarefas", cmd_resume),
        ("doctor", "verifica git, claude, chave e acesso à API", cmd_doctor),
    ):
        sub.add_parser(nome, help=ajuda).set_defaults(func=fn)

    args = parser.parse_args(argv)
    # Console do Windows costuma ser cp1252: nunca derrubar o agente por um acento no log.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    cfg = cfgmod.load()
    try:
        return int(args.func(cfg, args) or 0)
    except KeyboardInterrupt:
        print("\ninterrompido")
        return 130


if __name__ == "__main__":
    sys.exit(main())
