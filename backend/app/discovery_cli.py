"""CLI de discovery para execução NO HOST (onde o `claude` está logado).

Uso:
  uv run python -m app.discovery_cli run --source-name praxis-autonomous \\
      --agent code --domain praxis --capability pipeline \\
      --scope "internal/pipeline e internal/motor" --budget 5
"""

import argparse
import sys
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.jobs import defer_export
from app.models.knowledge import Source
from app.services.discovery import run_corroboration, run_discovery


def _resolver_source(db, args) -> uuid.UUID:
    if args.source_id:
        return uuid.UUID(args.source_id)
    src = db.scalar(select(Source).where(Source.name == args.source_name))
    if src is None:
        raise SystemExit(f"Source não encontrada: {args.source_name}")
    return src.id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="discovery")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="executa um discovery/corroboration run no host")
    p.add_argument("--source-id", default=None)
    p.add_argument("--source-name", default=None)
    p.add_argument("--agent", choices=["code", "test", "corroboration"], required=True)
    p.add_argument("--domain", required=True)
    p.add_argument("--capability", default=None)
    p.add_argument("--scope", default="todo o repositório")
    p.add_argument("--budget", type=float, default=5.0)
    p.add_argument("--max-candidates", type=int, default=40)
    p.add_argument("--timeout-min", type=int, default=30)
    p.add_argument("--actor", default="cli:discovery")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        source_id = _resolver_source(db, args)
        kwargs = dict(
            source_id=source_id, domain=args.domain, capability=args.capability,
            actor=args.actor, budget_usd=args.budget, timeout_min=args.timeout_min,
        )
        print(f"Iniciando {args.agent} discovery (budget US$ {args.budget:.2f})…")
        if args.agent == "corroboration":
            run = run_corroboration(db, **kwargs)
        else:
            run = run_discovery(
                db, agent=args.agent, scope_hint=args.scope,
                max_candidates=args.max_candidates, **kwargs,
            )

    print(f"Run {run.id}: {run.status}")
    print(f"  commit analisado : {run.commit}")
    print(f"  cli/modelo       : {run.cli_version} / {run.model} (effort {run.effort})")
    print(f"  custo            : US$ {run.cost_usd:.2f} em {run.num_turns} turno(s)")
    print(f"  candidates       : {run.candidates_created} criados, "
          f"{run.candidates_rejected} rejeitados, {run.duplicates_skipped} duplicados")
    print(f"  questions        : {run.questions_created}")
    print(f"  evidence         : {run.evidence_rejected} citação(ões) inválida(s) descartada(s)")
    print(f"  workspace limpo  : {run.workspace_clean}")
    print(f"  log              : {run.log_path}")
    if run.error:
        print(f"  erro             : {run.error}")
    if run.status == "succeeded":
        defer_export(trigger=f"discovery:{run.id}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
