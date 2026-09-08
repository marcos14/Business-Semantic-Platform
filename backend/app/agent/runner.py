"""Executa um pacote do servidor com o `claude` desta máquina."""

from pathlib import Path

from app.engines import claude_code


def options_from_packet(
    packet: dict, workdir: Path, logs_dir: Path, *, executable: str | list[str] = "claude"
) -> claude_code.RunOptions:
    tools = packet.get("tools")
    return claude_code.RunOptions(
        workdir=workdir,
        prompt=str(packet.get("prompt") or ""),
        logs_dir=logs_dir,
        label=str(packet.get("label") or "remoto")[:120],
        schema=packet.get("schema"),
        model=str(packet.get("model") or "opus"),
        effort=str(packet.get("effort") or "high"),
        budget_usd=packet.get("budget_usd"),
        timeout_min=int(packet.get("timeout_min") or 30),
        read_only=bool(packet.get("read_only", True)),
        tools=list(tools) if tools is not None else None,
        setting_sources=packet.get("setting_sources"),
        executable=executable,
    )


def execute(
    packet: dict, workdir: Path, logs_dir: Path, *, executable: str | list[str] = "claude"
) -> claude_code.RunResult:
    """Sempre `run_local`: o agente é o ponto final, nunca republica a tarefa."""
    op = options_from_packet(packet, workdir, logs_dir, executable=executable)
    return claude_code.run_local(op)
