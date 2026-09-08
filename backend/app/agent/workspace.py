"""Clone em cache do agente: o harness roda num checkout PRÓPRIO do agente, no commit
que o servidor fixou. O checkout de trabalho da pessoa nunca é tocado.

Origem do clone, nesta ordem: `git_url` da Source; caminho local configurado para a
source (`bsp-agent setup --source <id>=<caminho>`); `repository` da Source (só funciona
quando é um caminho alcançável desta máquina). Um caminho local configurado também serve
de `--reference` para não baixar de novo o que a pessoa já tem.
"""

import subprocess
from pathlib import Path

from app.agent.config import AgentConfig


class WorkspaceError(RuntimeError):
    pass


def _git(cwd: Path | str, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )
    if check and r.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} falhou: {r.stderr.strip()[:500]}")
    return r


def _has_commit(repo: Path, commit: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def clone_origin(cfg: AgentConfig, source: dict) -> tuple[str | None, str | None]:
    """(origem do clone, caminho local de referência) para esta source."""
    local = ((cfg.sources.get(str(source.get("id"))) or {}).get("path") or "").strip() or None
    origem = (source.get("git_url") or "").strip() or local or source.get("repository")
    return origem or None, local


def ensure_checkout(cfg: AgentConfig, source: dict) -> tuple[Path, Path]:
    """Garante o clone em cache no commit pedido. Devolve (cwd do harness, raiz do clone)."""
    sid = str(source.get("id") or "sem-id")
    commit = str(source.get("commit") or "").strip()
    if not commit:
        raise WorkspaceError("pacote sem commit fixado")
    origem, local = clone_origin(cfg, source)
    if not origem:
        raise WorkspaceError(
            "Source sem git_url e sem caminho local configurado nesta máquina "
            f"(bsp-agent setup --source {sid}=<caminho do repositório>)"
        )
    destino = cfg.repos_dir / sid
    if not (destino / ".git").exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        args = ["git", "clone", "--no-checkout", "--quiet"]
        if local and local != origem and Path(local).is_dir():
            args += ["--reference-if-able", local]
        args += [origem, str(destino)]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            raise WorkspaceError(f"git clone de {origem} falhou: {r.stderr.strip()[:500]}")
        # linhas e caminhos idênticos aos do servidor
        _git(destino, "config", "core.autocrlf", "false")
        _git(destino, "config", "core.longpaths", "true")
    if not _has_commit(destino, commit):
        _git(destino, "fetch", "--quiet", "origin", commit)
        if not _has_commit(destino, commit):
            _git(destino, "fetch", "--quiet", "--all")
        if not _has_commit(destino, commit):
            raise WorkspaceError(f"commit {commit[:12]} não encontrado em {origem}")
    # clone é do agente: pode ser forçado ao commit e limpo de restos de runs anteriores
    _git(destino, "checkout", "--quiet", "--detach", commit, check=True)
    _git(destino, "reset", "--hard", "--quiet", check=True)
    _git(destino, "clean", "-fdq")
    subdir = (source.get("subdir") or "").strip()
    cwd = destino / subdir if subdir else destino
    if not cwd.is_dir():
        raise WorkspaceError(f"subdiretório '{subdir}' não existe no commit {commit[:12]}")
    return cwd, destino


def status_snapshot(repo: Path) -> frozenset[str]:
    out = _git(repo, "status", "--porcelain", "--untracked-files=all").stdout
    return frozenset(ln for ln in out.splitlines() if ln.strip())


def is_clean(repo: Path, before: frozenset[str]) -> bool:
    return not (status_snapshot(repo) - before)


def head_commit(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()
