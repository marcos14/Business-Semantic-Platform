"""Broker do executor remoto: roda DENTRO do worker, no lugar do `claude -p` local.

`claude_code.run()` chama `run_remote()` quando `HARNESS_EXECUTOR=remote`. O broker
publica a chamada como `HarnessTask`, espera um agente concluir e devolve um `RunResult`
idêntico ao do executor local — o resto do pipeline (ingestão, verificação de evidência,
follow-ups, cascata) não sabe onde o harness rodou.

A espera é síncrona: um job do Procrastinate fica `doing` enquanto o agente trabalha, o
que mantém a semântica de hoje (um job = um run). O paralelismo vem da concorrência do
worker (`--concurrency N`): N tarefas em voo para N agentes.
"""

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.db import SessionLocal
from app.engines import claude_code
from app.harness import service
from app.models.harness import HarnessTask

log = logging.getLogger(__name__)


def run_remote(op: claude_code.RunOptions) -> claude_code.RunResult:
    with SessionLocal() as db:
        task = service.create_task(db, op)
        task_id = task.id
        online = service.count_online_agents(db)
    if online == 0:
        log.warning(
            "tarefa %s (%s) publicada sem nenhum agente online; esperando até %ss",
            task_id, op.label, settings.harness_remote_wait_seconds,
        )
    else:
        log.info("tarefa %s (%s) publicada; %d agente(s) online", task_id, op.label, online)

    prazo = time.monotonic() + settings.harness_remote_wait_seconds
    intervalo = max(0.05, float(settings.harness_poll_seconds))
    while True:
        with SessionLocal() as db:
            service.sweep_leases(db)
            task = db.get(HarnessTask, task_id)
            if task is None:
                return _erro(op, "tarefa removida do banco durante a espera")
            if task.status in service.TERMINAL:
                return _to_result(task, op)
            if time.monotonic() > prazo:
                service.cancel_task(
                    db, task,
                    f"prazo de {settings.harness_remote_wait_seconds}s esgotado sem agente "
                    "concluir (nenhum agente online ou todos limitados?)",
                )
                return _to_result(task, op)
        time.sleep(intervalo)


def _erro(op: claude_code.RunOptions, motivo: str) -> claude_code.RunResult:
    return claude_code.RunResult(
        is_error=True, subtype="executor remoto", result_text=motivo, structured=None,
        cost_usd=0.0, num_turns=0, session_id=None, log_path="",
        cli_version="remoto", prompt_hash=claude_code.prompt_hash(op.prompt, op.schema),
    )


def _to_result(task: HarnessTask, op: claude_code.RunOptions) -> claude_code.RunResult:
    if task.status != "succeeded" or not task.result:
        motivo = task.error or (
            "cancelada" if task.status == "cancelled" else "sem resultado do agente"
        )
        return _erro(op, f"tarefa {task.status}: {motivo}")
    log_path = _persist_log(op, task)
    res = claude_code.result_from_dict(
        task.result, log_path=str(log_path),
        prompt_hash=claude_code.prompt_hash(op.prompt, op.schema),
    )
    res.executed_by = task.executed_by
    return res


def _persist_log(op: claude_code.RunOptions, task: HarnessTask) -> Path:
    """O log .jsonl do agente vai para o mesmo diretório de logs do worker (audit §87)."""
    op.logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    log_path = op.logs_dir / f"{op.label}-{ts}.jsonl"
    conteudo = task.log_text or ""
    if not conteudo:
        conteudo = f"# sem log do agente; resultado: {task.result}\n"
    log_path.write_text(conteudo, encoding="utf-8")
    return log_path
