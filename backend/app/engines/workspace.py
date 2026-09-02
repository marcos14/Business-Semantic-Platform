"""Workspace descartável para discovery: clone efêmero + verificação pós-run.

A garantia de somente-leitura sobre a fonte legada é o DESCARTE do clone, não a
flag do harness (best-effort). A verificação git pós-run detecta e registra
qualquer escrita indevida.
"""

import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Workspace:
    path: Path
    commit: str  # HEAD resolvido — vai para a evidence (§23)
    branch: str | None


def _git(cwd: Path | str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )


def create(repository: str, branch: str | None = None, commit: str | None = None) -> Workspace:
    repo_src = Path(repository)
    if not (repo_src / ".git").exists():
        raise RuntimeError(f"Repositório git não encontrado: {repository}")
    tmp = Path(tempfile.mkdtemp(prefix="bsp-discovery-"))
    clone_args = ["clone", "--no-hardlinks", "--quiet"]
    if branch and not commit:
        clone_args += ["--branch", branch]
    r = subprocess.run(
        ["git", *clone_args, str(repo_src), str(tmp / "repo")],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"git clone falhou: {r.stderr}")
    ws = tmp / "repo"
    if commit:
        co = _git(ws, "checkout", "--quiet", commit)
        if co.returncode != 0:
            destroy(Workspace(ws, "", branch))
            raise RuntimeError(f"git checkout {commit} falhou: {co.stderr}")
    head = _git(ws, "rev-parse", "HEAD").stdout.strip()
    return Workspace(path=ws, commit=head, branch=branch)


def is_clean(ws: Workspace) -> bool:
    """Verificação pós-run: o harness (somente leitura) não deve ter sujado o clone."""
    return not _git(ws.path, "status", "--porcelain").stdout.strip()


def _on_rm_error(func, path, _exc):
    # .git no Windows tem arquivos readonly
    Path(path).chmod(stat.S_IWRITE)
    func(path)


def destroy(ws: Workspace) -> None:
    shutil.rmtree(ws.path.parent, onexc=_on_rm_error)


def read_lines(ws: Workspace, file: str, start: int, end: int) -> str | None:
    """Extrai o trecho REAL do arquivo (anti-alucinação: excerpt vem do fonte, não do LLM)."""
    alvo = (ws.path / file).resolve()
    try:
        alvo.relative_to(ws.path.resolve())  # bloqueia path traversal
    except ValueError:
        return None
    if not alvo.is_file():
        return None
    try:
        linhas = alvo.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if not (1 <= start <= end <= len(linhas)):
        return None
    return "\n".join(linhas[start - 1 : min(end, start + 39)])
