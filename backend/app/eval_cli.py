"""CLI do eval de Semantic Reconstruction Accuracy (§82).

Uso:
  uv run python -m app.eval_cli run --capability demand-pipeline \\
      --gold ../docs/eval/praxis-gold.yaml [--include-candidates]
"""

import argparse
import sys

from app.db import SessionLocal
from app.services.evaluator import run_eval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run")
    p.add_argument("--gold", required=True)
    p.add_argument("--capability", required=True)
    p.add_argument("--include-candidates", action="store_true")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        s = run_eval(
            db,
            gold_path=args.gold,
            capability=args.capability,
            include_candidates=args.include_candidates,
        )
    print(f"Eval {s['capability']} (candidates={s['include_candidates']})")
    print(f"  package: {s['package_stats']}")
    print(f"  perguntas: {s['total_questions']}")
    for classe, n in s["counts"].items():
        print(f"    {classe}: {n}")
    print(f"  accuracy (estrita): {s['accuracy_strict']:.1%}")
    print(f"  accuracy (crédito parcial): {s['accuracy_partial_credit']:.1%}")
    print(f"  alucinações (§83): {s['hallucinations']}")
    print(f"  relatório: {s['report_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
