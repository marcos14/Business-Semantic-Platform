"""Workspace de discovery: onde o harness lê a fonte legada.

Dois modos (settings.discovery_workspace_mode):

- **inplace** (padrão): o harness roda DIRETO no repositório original. A garantia de
  somente-leitura vem do harness restrito a ferramentas de leitura (Read/Grep/Glob, sem
  Bash/Edit/Write) e da verificação pós-run: o `git status` é fotografado antes e depois,
  e qualquer arquivo novo/alterado nesse intervalo marca o run como `workspace sujo`.
  Evita copiar repositórios de vários GB a cada run.
- **clone**: cópia descartável por run (isolamento por descarte). Quando a Source aponta
  para um subdiretório, o clone usa sparse-checkout só dele.

Em ambos, a Source pode apontar para um SUBDIRETÓRIO do repositório (ex.: `<repo>/source`):
o workspace (cwd do harness, base das citações de evidence) é esse subdiretório.
"""

import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Workspace:
    path: Path  # cwd do harness e base das citações (raiz do clone ou subdiretório)
    commit: str  # HEAD resolvido — vai para a evidence (§23)
    branch: str | None
    root: Path | None = None  # diretório temporário que contém o clone (removido no destroy)
    subdir: str | None = None  # subdiretório relativo à raiz git, quando houver
    inplace: bool = False
    repo_root: Path | None = None  # raiz git (inplace)
    status_before: frozenset[str] = field(default_factory=frozenset)


def _git(cwd: Path | str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )


def _resolver_raiz(repository: str) -> tuple[Path, str | None]:
    """Localiza a raiz git do caminho informado e o subdiretório relativo (ou None)."""
    alvo = Path(repository)
    if not alvo.is_dir():
        raise RuntimeError(f"Diretório não encontrado: {repository}")
    top = _git(alvo, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or not top.stdout.strip():
        raise RuntimeError(
            f"Repositório git não encontrado: {repository} (nem em diretórios acima)"
        )
    raiz = Path(top.stdout.strip())
    rel = os.path.relpath(alvo.resolve(), raiz.resolve())
    if rel.startswith(".."):
        raise RuntimeError(f"{repository} está fora da raiz git {raiz}")
    subdir = None if rel in (".", "") else Path(rel).as_posix()
    return raiz, subdir


def _status_snapshot(repo_root: Path) -> frozenset[str]:
    out = _git(repo_root, "status", "--porcelain", "--untracked-files=all").stdout
    return frozenset(ln for ln in out.splitlines() if ln.strip())


# ---------- modo inplace ----------


def open_inplace(repository: str) -> Workspace:
    """Usa o repositório original como workspace (sem cópia). branch/commit da Source são
    informativos: não fazemos checkout no repositório do usuário."""
    raiz, subdir = _resolver_raiz(repository)
    head = _git(raiz, "rev-parse", "HEAD")
    if head.returncode != 0 or not head.stdout.strip():
        raise RuntimeError(f"Repositório sem commits: {raiz} ({head.stderr.strip()})")
    branch = _git(raiz, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or None
    path = raiz / subdir if subdir else raiz
    return Workspace(
        path=path, commit=head.stdout.strip(), branch=branch, root=None, subdir=subdir,
        inplace=True, repo_root=raiz, status_before=_status_snapshot(raiz),
    )


# ---------- modo clone ----------


def create(repository: str, branch: str | None = None, commit: str | None = None) -> Workspace:
    repo_src, subdir = _resolver_raiz(repository)
    tmp = Path(tempfile.mkdtemp(prefix="bsp-discovery-"))
    clone_args = ["clone", "--no-hardlinks", "--quiet"]
    if subdir:
        clone_args.append("--no-checkout")  # materializa só o subdiretório (sparse) abaixo
    if branch and not commit:
        clone_args += ["--branch", branch]
    r = subprocess.run(
        ["git", *clone_args, str(repo_src), str(tmp / "repo")],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        shutil.rmtree(tmp, onexc=_on_rm_error)
        raise RuntimeError(f"git clone falhou: {r.stderr}")
    ws_root = tmp / "repo"
    parcial = Workspace(path=ws_root, commit="", branch=branch, root=tmp, subdir=subdir)

    if subdir:
        sp = _git(ws_root, "sparse-checkout", "set", "--cone", subdir)
        if sp.returncode != 0:
            destroy(parcial)
            raise RuntimeError(f"git sparse-checkout falhou: {sp.stderr}")
    if commit or subdir:
        co = _git(ws_root, "checkout", "--quiet", commit or "HEAD")
        if co.returncode != 0:
            destroy(parcial)
            raise RuntimeError(f"git checkout {commit or 'HEAD'} falhou: {co.stderr}")

    head = _git(ws_root, "rev-parse", "HEAD").stdout.strip()
    path = ws_root / subdir if subdir else ws_root
    if not path.is_dir():
        destroy(parcial)
        raise RuntimeError(
            f"Subdiretório '{subdir}' não existe no commit {head[:8]} do repositório {repo_src}"
        )
    return Workspace(path=path, commit=head, branch=branch, root=tmp, subdir=subdir)


# ---------- API comum ----------


def acquire(
    repository: str,
    branch: str | None = None,
    commit: str | None = None,
    mode: str | None = None,
) -> Workspace:
    """Abre o workspace conforme o modo configurado (inplace | clone)."""
    from app.config import settings

    modo = (mode or settings.discovery_workspace_mode or "inplace").lower()
    if modo == "clone":
        return create(repository, branch=branch, commit=commit)
    if modo == "inplace":
        return open_inplace(repository)
    raise RuntimeError(f"discovery_workspace_mode inválido: {modo}")


def is_clean(ws: Workspace) -> bool:
    """Verificação pós-run: o harness (somente leitura) não deve ter alterado nada.

    inplace: compara o `git status` de antes e depois (o repositório do usuário pode já
    estar sujo; o que importa é o que MUDOU durante o run)."""
    if ws.inplace:
        depois = _status_snapshot(ws.repo_root or ws.path)
        return not (depois - ws.status_before)
    return not _git(ws.path, "status", "--porcelain").stdout.strip()


def _on_rm_error(func, path, _exc):
    # .git no Windows tem arquivos readonly
    Path(path).chmod(stat.S_IWRITE)
    func(path)


def destroy(ws: Workspace) -> None:
    if ws.inplace:
        return  # nada a remover: é o repositório do usuário
    alvo = ws.root if ws.root is not None else ws.path.parent
    shutil.rmtree(alvo, onexc=_on_rm_error)


def list_files(
    ws: Workspace, extensions: set[str] | None = None, prefix: str | None = None
) -> list[str]:
    """Arquivos-fonte do workspace (relativos a ws.path, separador '/'), via git.

    inplace inclui arquivos não rastreados (não ignorados): o que está no disco é o que
    o harness lê. clone lista só o que está no commit."""
    args = ["ls-files", "--cached"]
    if ws.inplace:
        args += ["--others", "--exclude-standard"]
    out = _git(ws.path, *args).stdout
    exts = {e.lower() for e in extensions} if extensions else None
    arquivos = []
    for ln in out.splitlines():
        p = ln.strip().replace("\\", "/")
        if not p:
            continue
        if prefix and not p.startswith(prefix):
            continue
        if exts and Path(p).suffix.lower() not in exts:
            continue
        if not (ws.path / p).is_file():
            continue  # rastreado mas apagado do disco (inplace)
        arquivos.append(p)
    return sorted(set(arquivos))


def read_text(ws: Workspace, file: str, max_chars: int | None = None) -> tuple[str, int, bool]:
    """Conteúdo do arquivo (com traversal bloqueado): (texto, total_de_linhas, truncado)."""
    alvo = (ws.path / file).resolve()
    alvo.relative_to(ws.path.resolve())  # ValueError se sair do workspace
    texto = alvo.read_text(encoding="utf-8", errors="replace")
    linhas = texto.count("\n") + (0 if texto.endswith("\n") or not texto else 1)
    if max_chars and len(texto) > max_chars:
        return texto[:max_chars], linhas, True
    return texto, linhas, False


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
