"""Export canônico → YAML + Git (D3 da arquitetura).

Reconciliação idempotente: o export sincroniza o repo com o estado do banco
(escreve/atualiza/remove YAML) e comita apenas se houver diff. Qualquer
gatilho perdido converge no próximo export — drift entre Postgres e Git é
estruturalmente impossível de persistir. Escritor único via fila serializada.
"""

import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.canonical.serializer import atom_path, atom_to_dict, to_yaml
from app.kernel.ir.envelope import LifecycleStatus
from app.models.knowledge import AtomRelation, KnowledgeAtom

EXPORTED_STATUSES = (str(LifecycleStatus.CANONICAL), str(LifecycleStatus.SUPERSEDED))

_GIT_IDENTITY = [
    "-c",
    "user.name=BSP Canonical Exporter",
    "-c",
    "user.email=bsp-worker@local",
]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *_GIT_IDENTITY, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def export_canonical(db: Session, repo_path: str | Path, *, trigger: str = "manual") -> dict:
    repo = Path(repo_path).resolve()
    if not (repo / ".git").exists():
        raise RuntimeError(f"canonical-repo não é um repositório git: {repo}")

    atoms = db.scalars(
        select(KnowledgeAtom)
        .where(KnowledgeAtom.status.in_(EXPORTED_STATUSES))
        .options(selectinload(KnowledgeAtom.evidence_links))
        .order_by(KnowledgeAtom.id)
    ).all()

    expected: set[Path] = set()
    for atom in atoms:
        evidence = [
            {
                "id": str(link.evidence.id),
                "type": link.evidence.type,
                "relation": link.relation,
                "summary": link.evidence.summary,
                "location": link.evidence.location,
                "source_id": str(link.evidence.source_id) if link.evidence.source_id else None,
            }
            for link in atom.evidence_links
        ]
        relations = [
            {"type": r.type, "to": r.to_atom}
            for r in db.scalars(select(AtomRelation).where(AtomRelation.from_atom == atom.id))
        ]
        path = atom_path(repo, atom)
        expected.add(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = to_yaml(atom_to_dict(atom, evidence, relations))
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8", newline="\n")

    # remove YAML de atoms que não são mais canônicos (nunca toca .git/README)
    removed = 0
    for f in repo.rglob("*.yaml"):
        if ".git" in f.parts:
            continue
        if f not in expected:
            f.unlink()
            removed += 1

    status = _git(repo, "status", "--porcelain")
    if not status.stdout.strip():
        return {"exported": len(atoms), "removed": removed, "changed": False, "commit": None}

    _git(repo, "add", "-A")
    msg = f"Export canonical: {len(atoms)} atom(s) [{trigger}]"
    commit = _git(repo, "commit", "-m", msg)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit falhou: {commit.stderr or commit.stdout}")
    head = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    return {"exported": len(atoms), "removed": removed, "changed": True, "commit": head}
