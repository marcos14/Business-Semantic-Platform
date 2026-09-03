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

    pi = sub.add_parser("inventory", help="inventaria os fontes da source (lotes sequenciais)")
    pi.add_argument("--source-id", default=None)
    pi.add_argument("--source-name", default=None)
    pi.add_argument("--domain", required=True)
    pi.add_argument("--prefix", default=None, help="só arquivos sob este prefixo")
    pi.add_argument("--max-files", type=int, default=None)
    pi.add_argument("--all", action="store_true", help="re-inventaria também os já feitos")
    pi.add_argument("--budget", type=float, default=3.0, help="US$ por lote")
    pi.add_argument("--actor", default="cli:inventory")

    pc = sub.add_parser("campaign", help="discovery dirigido: um turno por arquivo × capability")
    pc.add_argument("--source-id", default=None)
    pc.add_argument("--source-name", default=None)
    pc.add_argument("--domain", required=True)
    pc.add_argument("--capability", required=True)
    pc.add_argument("--min-relevance", type=int, default=2)
    pc.add_argument("--max-files", type=int, default=None)
    pc.add_argument("--budget", type=float, default=3.0, help="US$ por arquivo/faixa")
    pc.add_argument("--max-candidates", type=int, default=12)
    pc.add_argument("--actor", default="cli:campaign")
    args = parser.parse_args(argv)

    if args.command == "inventory":
        return _cmd_inventory(args)
    if args.command == "campaign":
        return _cmd_campaign(args)

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


def _cmd_inventory(args) -> int:
    from app.models.knowledge import Source
    from app.services.inventory import inventory_summary, plan_inventory, run_inventory_batch

    batch_id = uuid.uuid4()
    with SessionLocal() as db:
        source_id = _resolver_source(db, args)
        src = db.get(Source, source_id)
        lotes, total = plan_inventory(
            db, src, prefix=args.prefix, max_files=args.max_files, only_missing=not args.all
        )
        if not lotes:
            print("Nada a inventariar (todos já feitos? prefixo/extensões?).")
            return 0
        print(f"Inventário: {total} arquivo(s) em {len(lotes)} lote(s), batch {batch_id}")
        custo = 0.0
        for i, lote in enumerate(lotes, 1):
            run = run_inventory_batch(
                db, source_id=source_id, domain=args.domain, files=lote, actor=args.actor,
                batch_id=batch_id, budget_usd=args.budget,
            )
            custo += run.cost_usd
            print(f"  lote {i}/{len(lotes)}: {run.status} · {run.candidates_created}/{len(lote)} "
                  f"arquivos · US$ {run.cost_usd:.2f}" + (f" · {run.error}" if run.error else ""))
            if run.status in ("limit", "auth_failed"):
                print("  interrompido: franquia/autenticação — rode de novo mais tarde.")
                return 1
        s = inventory_summary(db, source_id)
    print(f"Total US$ {custo:.2f} · {s['files']} arquivo(s) inventariados, "
          f"{s['files_with_capability']} com capability, {len(s['suggestions'])} sugestão(ões)")
    for c in s["capabilities"]:
        print(f"  {c['slug']:<30} {c['files']} arquivo(s)")
    return 0


def _cmd_campaign(args) -> int:
    from app.config import settings
    from app.models.knowledge import Source
    from app.services.discovery import plan_directed, run_directed_discovery

    batch_id = uuid.uuid4()
    with SessionLocal() as db:
        source_id = _resolver_source(db, args)
        src = db.get(Source, source_id)
        plano = plan_directed(
            db, src, capability=args.capability, min_relevance=args.min_relevance,
            max_files=args.max_files,
        )
        if not plano:
            print("Nenhum arquivo inventariado para esta capability — rode `inventory` antes.")
            return 1
        print(f"Campanha {args.capability}: {len(plano)} turno(s), batch {batch_id}")
        fila = list(plano)
        followups = 0
        custo, cands = 0.0, 0
        feitos: set[str] = set()
        while fila:
            t = fila.pop(0)
            run = run_directed_discovery(
                db, source_id=source_id, domain=args.domain, capability=args.capability,
                file=t["file"], start_line=t["start_line"], end_line=t["end_line"],
                actor=args.actor, batch_id=batch_id, is_followup=t.get("followup", False),
                budget_usd=args.budget, max_candidates=args.max_candidates,
            )
            feitos.add(t["file"])
            custo += run.cost_usd
            cands += run.candidates_created
            print(f"  {t['file']} [{run.line_range}]: {run.status} · {run.candidates_created} "
                  f"candidates · US$ {run.cost_usd:.2f}" + (f" · {run.error}" if run.error else ""))
            if run.status in ("limit", "auth_failed"):
                print("  interrompido: franquia/autenticação — rode de novo mais tarde.")
                return 1
            for fu in getattr(run, "followups", []) or []:
                if fu["file"] in feitos or followups >= settings.discovery_followups_max:
                    continue
                if any(x["file"] == fu["file"] for x in fila):
                    continue
                fila.append({**fu, "followup": True})
                followups += 1
        if cands:
            defer_export(trigger=f"campaign:{batch_id}")
    print(f"Total US$ {custo:.2f} · {cands} candidates · {followups} follow-up(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
