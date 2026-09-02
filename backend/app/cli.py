"""CLI `semantic` (PRD §59). Uso: `uv run semantic compile [caminho-do-repo]`."""

import argparse
import sys

from app.canonical.compiler import compile_repo
from app.config import settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="semantic")
    sub = parser.add_subparsers(dest="command", required=True)
    p_compile = sub.add_parser("compile", help="valida o canonical-repo (schema + linter)")
    p_compile.add_argument(
        "path", nargs="?", default=settings.canonical_repo_path, help="caminho do canonical-repo"
    )
    args = parser.parse_args(argv)

    report = compile_repo(args.path)
    print(f"semantic compile — {args.path}")
    print(f"  arquivos: {report.files} | atoms válidos: {report.atoms}")
    for k, v in report.metrics.get("atoms_por_kind", {}).items():
        print(f"    {k}: {v}")
    for err in report.schema_errors:
        print(f"  [schema] {err}")
    for f in report.findings:
        print(f"  [{f.severity}] {f.code} {f.atom_id}: {f.message}")
    if report.ok:
        print("  OK — repositório canônico válido")
        return 0
    print(
        f"  FALHOU — {len(report.schema_errors)} erro(s) de schema, "
        f"{len(report.lint_errors)} erro(s) de linter"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
