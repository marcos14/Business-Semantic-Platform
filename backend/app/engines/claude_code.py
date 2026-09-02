"""Porta CodeAnalysisEngine: Claude Code headless (`claude -p`) como subprocesso.

Porte do padrão `motor` do praxis-autonomous (validado em produção):
stream-json, --json-schema com resgate via --resume, modo somente leitura via
--disallowedTools, budget por run, log .jsonl completo, detecção de limite de
franquia e falha de autenticação, kill da árvore de processos no timeout.

Usa a credencial ambiente da máquina (`claude` logado no PATH) — decisão
registrada no plano; sem gestão de assinatura/API key pela plataforma.
"""

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

RESCUE_SUBTYPE = "error_max_structured_output_retries"

RESCUE_PROMPT = (
    "Sua execução anterior terminou sem conseguir emitir a saída estruturada: as chamadas "
    "da ferramenta StructuredOutput chegaram sem todos os campos obrigatórios. O trabalho "
    "já está feito acima — NÃO o refaça e não use outras ferramentas. Chame a ferramenta "
    "StructuredOutput UMA única vez agora, com o objeto completo que satisfaz o schema: "
    "inclua TODOS os campos obrigatórios e seja conciso nos campos de texto."
)

READ_ONLY_TOOLS = ["Edit", "Write", "NotebookEdit", "Bash(git commit*)", "Bash(git push*)"]


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
    # comando do harness; lista permite fake em teste: [sys.executable, "fake_claude.py"]
    executable: str | list[str] = "claude"


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


def run(op: RunOptions) -> RunResult:
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
        if rescue.is_error and not rescue.result_text.strip():
            rescue.result_text = res.result_text
        return rescue
    return res


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
    if op.read_only:
        args += ["--disallowedTools", *READ_ONLY_TOOLS]

    op.logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    log_path = op.logs_dir / f"{op.label}-{ts}.jsonl"
    p_hash = prompt_hash(op.prompt, op.schema)
    version = cli_version(op.executable)

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
        )

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
