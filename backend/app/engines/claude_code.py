"""Porta CodeAnalysisEngine: Claude Code headless (`claude -p`) como subprocesso.

Porte do padrão `motor` do praxis-autonomous (validado em produção):
stream-json, --json-schema com resgate via --resume, modo somente leitura via
--disallowedTools, budget por run, log .jsonl completo, detecção de limite de
franquia e falha de autenticação, kill da árvore de processos no timeout.

Usa a credencial ambiente da máquina (`claude` logado no PATH, ou ANTHROPIC_API_KEY) —
decisão registrada no plano; sem gestão de assinatura/API key pela plataforma.

Dois executores (settings.harness_executor):
- **local** (padrão): `run()` chama o `claude` desta máquina, como sempre.
- **remote**: `run()` publica a chamada como tarefa e espera um agente `bsp-agent`
  (máquina de um membro da equipe, com a própria chave) devolver o resultado. O agente,
  por sua vez, chama `run_local()` — este módulo não depende do resto do backend.
"""

import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

RESCUE_SUBTYPE = "error_max_structured_output_retries"

RESCUE_PROMPT = (
    "Sua execução anterior terminou sem conseguir emitir a saída estruturada: as chamadas "
    "da ferramenta StructuredOutput chegaram sem todos os campos obrigatórios. O trabalho "
    "já está feito acima — NÃO o refaça e não use outras ferramentas. Chame a ferramenta "
    "StructuredOutput UMA única vez agora, com o objeto completo que satisfaz o schema: "
    "inclua TODOS os campos obrigatórios e seja conciso nos campos de texto."
)

READ_ONLY_TOOLS = ["Edit", "Write", "NotebookEdit", "Bash(git commit*)", "Bash(git push*)"]
# Ferramentas quando o harness roda DENTRO do repositório original (modo inplace):
# só leitura, sem Bash — nenhum comando pode tocar a árvore do usuário.
INPLACE_TOOLS = ["Read", "Grep", "Glob"]


@dataclass
class RemoteContext:
    """O que um agente remoto precisa para reproduzir o workspace deste run."""

    source_id: str
    repository: str | None  # caminho no servidor (informativo para o agente)
    git_url: str | None  # de onde o agente clona; None = usa `repository`
    subdir: str | None  # cwd do harness relativo à raiz git
    commit: str  # o agente faz checkout EXATAMENTE deste commit
    branch: str | None


@dataclass
class RunOptions:
    workdir: Path
    prompt: str
    logs_dir: Path
    label: str
    schema: dict | None = None
    model: str = "opus"
    effort: str = "high"
    budget_usd: float | None = None
    timeout_min: int = 30
    read_only: bool = True
    # Lista fechada de ferramentas (`--tools`); None = padrão do harness menos READ_ONLY_TOOLS
    tools: list[str] | None = None
    # Fontes de settings carregadas pelo harness. "user" evita que hooks/permissões do
    # repositório ANALISADO (.claude/ do legado) sejam executados pelo agente.
    setting_sources: str | None = "user"
    # comando do harness; lista permite fake em teste: [sys.executable, "fake_claude.py"]
    executable: str | list[str] = "claude"
    # Executor remoto: contexto do workspace e run auditado (ignorados no executor local).
    remote: RemoteContext | None = None
    run_id: str | None = None


def tools_for(inplace: bool) -> list[str] | None:
    """Ferramentas do harness conforme o workspace: inplace = só leitura, sem Bash."""
    return list(INPLACE_TOOLS) if inplace else None


def remote_context(ws, source) -> RemoteContext:
    """Contexto remoto a partir do workspace aberto e da Source (qualquer modo)."""
    return RemoteContext(
        source_id=str(source.id),
        repository=source.repository,
        git_url=getattr(source, "git_url", None) or None,
        subdir=ws.subdir,
        commit=ws.commit,
        branch=ws.branch,
    )


@dataclass
class RunResult:
    is_error: bool
    subtype: str | None
    result_text: str
    structured: dict | None
    cost_usd: float
    num_turns: int
    session_id: str | None
    log_path: str
    cli_version: str
    prompt_hash: str
    session_limit: bool = False
    limit_detail: str | None = None
    auth_failed: bool = False
    stderr_tail: str = ""
    progress: list[str] = field(default_factory=list)
    duration_ms: int | None = None
    # Executor remoto: o agente reporta se o clone ficou limpo e quem executou.
    workspace_clean: bool | None = None
    executed_by: str | None = None


RESULT_FIELDS = (
    "is_error", "subtype", "result_text", "structured", "cost_usd", "num_turns",
    "session_id", "cli_version", "prompt_hash", "session_limit", "limit_detail",
    "auth_failed", "stderr_tail", "progress", "duration_ms", "workspace_clean",
)


def result_to_dict(res: RunResult) -> dict:
    """Serialização do resultado para transporte agente → servidor (sem o log_path local)."""
    return {k: getattr(res, k) for k in RESULT_FIELDS}


def result_from_dict(d: dict, *, log_path: str, prompt_hash: str | None = None) -> RunResult:
    """Reconstrói o RunResult vindo de um agente. Campos ausentes ganham valor neutro."""
    structured = d.get("structured")
    return RunResult(
        is_error=bool(d.get("is_error")),
        subtype=d.get("subtype"),
        result_text=str(d.get("result_text") or ""),
        structured=structured if isinstance(structured, dict) else None,
        cost_usd=float(d.get("cost_usd") or 0.0),
        num_turns=int(d.get("num_turns") or 0),
        session_id=d.get("session_id"),
        log_path=log_path,
        cli_version=str(d.get("cli_version") or "desconhecida"),
        prompt_hash=prompt_hash or str(d.get("prompt_hash") or ""),
        session_limit=bool(d.get("session_limit")),
        limit_detail=d.get("limit_detail"),
        auth_failed=bool(d.get("auth_failed")),
        stderr_tail=str(d.get("stderr_tail") or ""),
        progress=list(d.get("progress") or []),
        duration_ms=d.get("duration_ms"),
        workspace_clean=d.get("workspace_clean"),
    )


def _session_limit(text: str) -> bool:
    t = text.lower()
    return ("session limit" in t or "usage limit" in t) and "reset" in t


def _auth_failed(text: str) -> bool:
    t = text.lower()
    return any(
        s in t
        for s in (
            "not logged in",
            "please run /login",
            "authentication_failed",
            "invalid api key",
            "oauth token has expired",
        )
    )


def is_rate_limited(text: str) -> bool:
    """Rate limit da API (chave própria): transitório, o agente tenta de novo depois."""
    t = (text or "").lower()
    return "rate_limit" in t or "rate limit" in t or "429" in t or "overloaded" in t


def _exe_list(executable: str | list[str]) -> list[str]:
    return [executable] if isinstance(executable, str) else list(executable)


@lru_cache(maxsize=8)
def _cli_version_cached(exe_key: tuple[str, ...]) -> str:
    try:
        out = subprocess.run(
            [*exe_key, "--version"], capture_output=True, text=True, timeout=30, shell=False
        )
        return (out.stdout or out.stderr).strip()[:100] or "desconhecida"
    except Exception:
        return "indisponível"


def cli_version(executable: str | list[str] = "claude") -> str:
    return _cli_version_cached(tuple(_exe_list(executable)))


def _kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        subprocess.run(["pkill", "-TERM", "-P", str(pid)], capture_output=True)


def prompt_hash(prompt: str, schema: dict | None) -> str:
    h = hashlib.sha256(prompt.encode())
    if schema:
        h.update(json.dumps(schema, sort_keys=True).encode())
    return h.hexdigest()[:16]


# ---------- franquia ----------

RESET_DEFAULT_SECONDS = 1800
RESET_MAX_SECONDS = 6 * 3600


def delay_until_reset(texto: str | None, agora=None) -> int:
    """Segundos até o reset da franquia, lidos da mensagem do harness
    ("You've hit your session limit · resets 10:30pm (America/Sao_Paulo)").
    Sem horário reconhecível → 30min. Evita o ciclo de tentar a cada 30min e
    bater no limite de novo (cada tentativa vira um run 'limit' na auditoria)."""
    if not texto:
        return RESET_DEFAULT_SECONDS
    m = re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", texto, re.I)
    if not m:
        return RESET_DEFAULT_SECONDS
    hora, minuto, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ampm == "pm" and hora < 12:
        hora += 12
    if ampm == "am" and hora == 12:
        hora = 0
    tz = None
    mtz = re.search(r"\(([A-Za-z_]+/[A-Za-z_]+)\)", texto)
    if mtz:
        try:
            tz = ZoneInfo(mtz.group(1))
        except Exception:
            tz = None
    agora = agora or datetime.now(tz)
    if tz is not None and agora.tzinfo is not None:
        agora = agora.astimezone(tz)
    alvo = agora.replace(hour=hora % 24, minute=minuto, second=0, microsecond=0)
    if alvo <= agora:
        alvo += timedelta(days=1)
    delta = int((alvo - agora).total_seconds()) + 60  # folga de 1min após o reset
    return max(60, min(delta, RESET_MAX_SECONDS))


# ---------- execução ----------


def _executor() -> str:
    """Executor configurado. Sem o backend (agente rodando fora do servidor) → local."""
    try:
        from app.config import settings

        return (settings.harness_executor or "local").strip().lower()
    except Exception:
        return "local"


def run(op: RunOptions) -> RunResult:
    """Ponto de entrada do backend: local (subprocesso aqui) ou remoto (agente)."""
    if _executor() == "remote":
        from app.harness.broker import run_remote

        return run_remote(op)
    return run_local(op)


def run_local(op: RunOptions) -> RunResult:
    """Chama o `claude` DESTA máquina (usado pelo worker local e pelo agente remoto)."""
    res = _run_once(op, resume_id=None)
    # Resgate (padrão Praxis): reemitir só a saída estruturada na MESMA sessão
    if (
        res.is_error
        and res.subtype == RESCUE_SUBTYPE
        and op.schema
        and res.session_id
    ):
        rescue_op = RunOptions(
            **{**op.__dict__, "prompt": RESCUE_PROMPT, "label": op.label + "-resgate"}
        )
        rescue = _run_once(rescue_op, resume_id=res.session_id)
        rescue.cost_usd += res.cost_usd
        rescue.num_turns += res.num_turns
        if res.duration_ms and rescue.duration_ms is not None:
            rescue.duration_ms += res.duration_ms
        if rescue.is_error and not rescue.result_text.strip():
            rescue.result_text = res.result_text
        return rescue
    return res


def probe(logs_dir: Path, executable: str | list[str] = "claude") -> RunResult:
    """Sonda mínima da franquia: um turno sem ferramentas e com budget irrisório.
    Serve para detectar que os créditos voltaram (ou que a conta foi trocada)."""
    try:
        from app.config import settings

        model = settings.harness_probe_model
    except Exception:
        model = "haiku"

    return _run_once(
        RunOptions(
            workdir=logs_dir if logs_dir.is_dir() else Path.cwd(),
            prompt="Responda apenas com a palavra OK.",
            logs_dir=logs_dir,
            label="probe-franquia",
            model=model,
            effort="low",
            budget_usd=0.05,
            timeout_min=3,
            read_only=True,
            tools=[],
            executable=executable,
        ),
        resume_id=None,
    )


def _run_once(op: RunOptions, resume_id: str | None) -> RunResult:
    args = [*_exe_list(op.executable), "-p", "--dangerously-skip-permissions",
            "--output-format", "stream-json", "--verbose"]
    if resume_id:
        args += ["--resume", resume_id]
    if op.model:
        args += ["--model", op.model]
    if op.effort:
        args += ["--effort", op.effort]
    if op.budget_usd:
        args += ["--max-budget-usd", f"{op.budget_usd:.2f}"]
    if op.schema:
        args += ["--json-schema", json.dumps(op.schema)]
    if op.tools is not None:
        args += ["--tools", ",".join(op.tools)]
    if op.read_only:
        args += ["--disallowedTools", *READ_ONLY_TOOLS]
    if op.setting_sources:
        args += ["--setting-sources", op.setting_sources]

    op.logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    log_path = op.logs_dir / f"{op.label}-{ts}.jsonl"
    p_hash = prompt_hash(op.prompt, op.schema)
    version = cli_version(op.executable)
    inicio = time.monotonic()

    proc = subprocess.Popen(
        args,
        cwd=str(op.workdir),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    result: RunResult | None = None
    session_id: str | None = None
    progress: list[str] = []
    try:
        # prompt via stdin (padrão Praxis); communicate lida com timeout
        stdout, stderr = proc.communicate(input=op.prompt, timeout=op.timeout_min * 60)
    except subprocess.TimeoutExpired:
        _kill_tree(proc.pid)
        proc.wait(timeout=30)
        return RunResult(
            is_error=True, subtype="timeout",
            result_text=f"claude excedeu o timeout de {op.timeout_min}min",
            structured=None, cost_usd=0.0, num_turns=0, session_id=None,
            log_path=str(log_path), cli_version=version, prompt_hash=p_hash,
            duration_ms=int((time.monotonic() - inicio) * 1000),
        )
    duration_ms = int((time.monotonic() - inicio) * 1000)

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(stdout)

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("session_id"):
            session_id = ev["session_id"]
        if ev.get("type") == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    progress.append(f"-> {c.get('name')}")
                elif c.get("type") == "text" and c.get("text", "").strip():
                    progress.append(c["text"].strip()[:200])
        elif ev.get("type") == "result":
            texto = ev.get("result") or ""
            if not texto.strip() and ev.get("errors"):
                texto = "; ".join(str(e) for e in ev["errors"])
            structured = ev.get("structured_output")
            result = RunResult(
                is_error=bool(ev.get("is_error")),
                subtype=ev.get("subtype"),
                result_text=texto,
                structured=structured if isinstance(structured, dict) else None,
                cost_usd=float(ev.get("total_cost_usd") or 0.0),
                num_turns=int(ev.get("num_turns") or 0),
                session_id=session_id,
                log_path=str(log_path),
                cli_version=version,
                prompt_hash=p_hash,
                progress=progress,
                duration_ms=duration_ms,
            )

    stderr_tail = "\n".join(stderr.splitlines()[-15:])
    if result is None:
        limite = _session_limit(stderr) or _session_limit(stdout)
        return RunResult(
            is_error=True,
            subtype="limite de sessão/uso" if limite else "sem evento de resultado",
            result_text=stderr_tail or "claude terminou sem evento de resultado",
            structured=None, cost_usd=0.0, num_turns=0, session_id=session_id,
            log_path=str(log_path), cli_version=version, prompt_hash=p_hash,
            session_limit=limite, limit_detail=stderr_tail if limite else None,
            auth_failed=_auth_failed(stderr) or _auth_failed(stdout),
            stderr_tail=stderr_tail,
            duration_ms=duration_ms,
        )

    # Limite/auth só são avaliados em runs COM erro: um resultado bem-sucedido cujo
    # CONTEÚDO menciona "session limit ... reset" (ex.: conhecimento extraído sobre
    # detecção de franquia) não pode virar falso positivo.
    if result.is_error:
        texto_total = result.result_text + "\n" + stderr
        if _session_limit(texto_total):
            result.session_limit = True
            result.limit_detail = next(
                (ln.strip() for ln in texto_total.splitlines() if _session_limit(ln)), None
            )
        if _auth_failed(texto_total):
            result.auth_failed = True
    result.stderr_tail = stderr_tail
    return result
