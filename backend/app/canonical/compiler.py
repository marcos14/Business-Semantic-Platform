"""`semantic compile` (PRD §59): valida o canonical-repo INDEPENDENTE do banco.

Lê apenas os YAML do repo — é a verificação cruzada contra drift (D3) e a
garantia de recoverability (§93): o repo sozinho precisa ser válido.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.kernel.errors import BodyValidationError
from app.kernel.ir.envelope import ATOM_ID_PATTERN
from app.kernel.ir.registry import validate_body
from app.kernel.linter import AtomView, Finding, RelationView, lint

REQUIRED_FIELDS = ("id", "kind", "title", "domain", "status", "version")


@dataclass
class CompileReport:
    files: int = 0
    atoms: int = 0
    schema_errors: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def lint_errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.schema_errors and not self.lint_errors


def compile_repo(repo_path: str | Path) -> CompileReport:
    repo = Path(repo_path).resolve()
    report = CompileReport()
    atoms: list[AtomView] = []
    relations: list[RelationView] = []
    supported: set[str] = set()
    seen_ids: dict[str, str] = {}

    for f in sorted(repo.rglob("*.yaml")):
        if ".git" in f.parts:
            continue
        report.files += 1
        rel = f.relative_to(repo).as_posix()
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            report.schema_errors.append(f"{rel}: YAML inválido — {e}")
            continue
        if not isinstance(data, dict):
            report.schema_errors.append(f"{rel}: conteúdo não é um mapeamento")
            continue

        faltando = [c for c in REQUIRED_FIELDS if not data.get(c)]
        if faltando:
            report.schema_errors.append(f"{rel}: campos obrigatórios ausentes: {faltando}")
            continue

        atom_id = str(data["id"])
        if not ATOM_ID_PATTERN.match(atom_id):
            report.schema_errors.append(f"{rel}: ID fora do padrão: {atom_id}")
        if atom_id in seen_ids:
            report.schema_errors.append(
                f"{rel}: ID duplicado ({atom_id} também em {seen_ids[atom_id]})"
            )
        seen_ids.setdefault(atom_id, rel)

        try:
            body = validate_body(str(data["kind"]), data.get("body") or {})
        except BodyValidationError as e:
            report.schema_errors.append(f"{rel}: {e}")
            continue

        atoms.append(
            AtomView(
                id=atom_id,
                kind=str(data["kind"]),
                status=str(data["status"]),
                capability=data.get("capability"),
                scope=data.get("scope"),
                body=body,
            )
        )
        for r in data.get("relations") or []:
            relations.append(RelationView(from_atom=atom_id, to_atom=r["to"], type=r["type"]))
        if any(e.get("relation") == "supports" for e in data.get("evidence") or []):
            supported.add(atom_id)

    report.atoms = len(atoms)
    report.findings = lint(atoms, relations, supported)
    por_kind: dict[str, int] = {}
    for a in atoms:
        por_kind[a.kind] = por_kind.get(a.kind, 0) + 1
    report.metrics = {"atoms_por_kind": dict(sorted(por_kind.items()))}
    return report
