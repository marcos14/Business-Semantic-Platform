"""Inventário de fontes (passo anterior ao discovery dirigido).

Enumeramos NÓS os arquivos-fonte da Source (git ls-files filtrado por extensão), montamos
lotes que cabem no prompt com o CONTEÚDO embutido e pedimos ao harness, por lote, um
resumo de negócio de cada arquivo e a ligação com as capabilities cadastradas no domain.
O agente não gasta turnos abrindo arquivo por arquivo; e capabilities que ele encontra no
código mas não existem no cadastro viram sugestões para o administrador.
"""

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import prompts
from app.config import settings
from app.engines import claude_code, workspace
from app.kernel.errors import KernelError, NotFoundError
from app.models.auth import Capability
from app.models.discovery import DiscoveryRun
from app.models.inventory import CapabilitySuggestion, SourceFile, SourceFileCapability
from app.models.knowledge import Source


def source_extensions() -> set[str]:
    return {
        e.strip().lower() for e in settings.discovery_source_extensions.split(",") if e.strip()
    }


def capabilities_of(db: Session, domain: str) -> list[dict]:
    caps = db.scalars(
        select(Capability).where(Capability.domain_slug == domain).order_by(Capability.slug)
    )
    return [{"slug": c.slug, "name": c.name, "description": c.description} for c in caps]


def _finish(db: Session, run: DiscoveryRun, status: str, error: str | None = None) -> DiscoveryRun:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(UTC)
    db.commit()
    return run


# ---------- planejamento ----------


def plan_inventory(
    db: Session,
    source: Source,
    *,
    prefix: str | None = None,
    max_files: int | None = None,
    only_missing: bool = True,
    batch_chars: int | None = None,
    file_max_chars: int | None = None,
) -> tuple[list[list[str]], int]:
    """Devolve (lotes de caminhos, total elegível). Cada lote cabe em `batch_chars`
    (conteúdo truncado por arquivo em `file_max_chars`)."""
    if not source.repository:
        raise NotFoundError("Source sem repositório")
    batch_chars = batch_chars or settings.inventory_batch_chars
    file_max_chars = file_max_chars or settings.inventory_file_max_chars

    ws = workspace.acquire(source.repository, source.branch, source.commit)
    try:
        arquivos = workspace.list_files(ws, source_extensions(), prefix)
        if only_missing:
            feitos = set(
                db.scalars(select(SourceFile.path).where(SourceFile.source_id == source.id))
            )
            arquivos = [a for a in arquivos if a not in feitos]
        if max_files:
            arquivos = arquivos[:max_files]
        tamanhos = {
            a: min(os.path.getsize(ws.path / a), file_max_chars) for a in arquivos
        }
    finally:
        workspace.destroy(ws)

    lotes: list[list[str]] = []
    atual: list[str] = []
    acumulado = 0
    for a in arquivos:
        t = tamanhos[a] + 200  # cabeçalho/cerca do bloco
        if atual and acumulado + t > batch_chars:
            lotes.append(atual)
            atual, acumulado = [], 0
        atual.append(a)
        acumulado += t
    if atual:
        lotes.append(atual)
    return lotes, len(arquivos)


# ---------- execução de um lote ----------


def run_inventory_batch(
    db: Session,
    *,
    source_id: uuid.UUID,
    domain: str,
    files: list[str],
    actor: str,
    batch_id: uuid.UUID | None = None,
    budget_usd: float | None = 3.0,
    model: str | None = None,  # padrão: settings.harness_model
    effort: str | None = None,  # padrão: settings.harness_inventory_effort
    timeout_min: int = 30,
    executable: str = "claude",
) -> DiscoveryRun:
    model = model or settings.harness_model
    effort = effort or settings.harness_inventory_effort
    source = db.get(Source, source_id)
    if source is None or not source.repository:
        raise NotFoundError("Source inexistente ou sem repositório")
    if not files:
        raise KernelError("Lote de inventário vazio")
    caps = capabilities_of(db, domain)
    if not caps:
        raise KernelError(
            f"Domain '{domain}' não tem capabilities cadastradas — o inventário liga arquivos "
            "a capabilities; cadastre-as primeiro (Admin)"
        )

    run = DiscoveryRun(
        source_id=source_id, agent="inventory", domain=domain, capability=None,
        model=model, effort=effort, created_by=actor, batch_id=batch_id,
        target_file=f"{len(files)} arquivo(s)",
    )
    try:
        ws = workspace.acquire(source.repository, source.branch, source.commit)
    except RuntimeError as e:
        db.add(run)
        return _finish(db, run, "failed", f"workspace: {e}")

    try:
        conteudos = []
        for f in files:
            try:
                texto, linhas, truncado = workspace.read_text(
                    ws, f, max_chars=settings.inventory_file_max_chars
                )
            except (OSError, ValueError):
                continue
            conteudos.append(
                {"path": f, "content": texto, "truncated": truncado, "lines": linhas,
                 "chars": len(texto)}
            )
        if not conteudos:
            db.add(run)
            return _finish(db, run, "failed", "nenhum arquivo do lote pôde ser lido")

        prompt = prompts.inventory_prompt(domain=domain, capabilities=caps, files=conteudos)
        run.commit = ws.commit
        run.prompt_hash = claude_code.prompt_hash(prompt, prompts.INVENTORY_SCHEMA)
        db.add(run)
        db.commit()

        res = claude_code.run(
            claude_code.RunOptions(
                workdir=ws.path,
                prompt=prompt,
                schema=prompts.INVENTORY_SCHEMA,
                logs_dir=Path(settings.discovery_logs_dir),
                label=f"inventory-{str(run.id)[:8]}",
                model=model,
                effort=effort,
                budget_usd=budget_usd,
                timeout_min=timeout_min,
                executable=executable,
                tools=claude_code.tools_for(ws.inplace),
            )
        )
        run.cli_version = res.cli_version
        run.session_id = res.session_id
        run.log_path = res.log_path
        run.cost_usd = res.cost_usd
        run.num_turns = res.num_turns
        run.workspace_clean = "yes" if workspace.is_clean(ws) else "no"

        if res.session_limit:
            return _finish(db, run, "limit", res.limit_detail or res.result_text)
        if res.auth_failed:
            return _finish(db, run, "auth_failed", res.result_text)
        if res.is_error or not res.structured:
            return _finish(db, run, "failed", f"{res.subtype or 'erro'}: {res.result_text[:800]}")

        _ingest_inventory(db, run, source, domain, conteudos, caps, res.structured)
        return _finish(db, run, "succeeded")
    finally:
        workspace.destroy(ws)


def _ingest_inventory(
    db: Session,
    run: DiscoveryRun,
    source: Source,
    domain: str,
    conteudos: list[dict],
    caps: list[dict],
    payload: dict,
) -> None:
    por_path = {c["path"]: c for c in conteudos}
    slugs_validos = {c["slug"] for c in caps}
    vistos: set[str] = set()

    for item in payload.get("files", []):
        path = str(item.get("path", "")).replace("\\", "/").strip()
        meta = por_path.get(path)
        if meta is None or path in vistos:
            run.candidates_rejected += 1  # caminho que não estava no lote / repetido
            continue
        vistos.add(path)

        sf = db.scalar(
            select(SourceFile).where(SourceFile.source_id == source.id, SourceFile.path == path)
        )
        if sf is None:
            sf = SourceFile(source_id=source.id, path=path)
            db.add(sf)
            db.flush()
        sf.language = prompts.language_of(path)
        sf.lines = meta["lines"]
        sf.chars = meta["chars"]
        sf.summary = (item.get("summary") or "").strip()[:2000] or None
        sf.commit = run.commit
        sf.run_id = run.id
        sf.inventoried_at = datetime.now(UTC)

        # religa do zero: o inventário mais recente manda
        for link in db.scalars(
            select(SourceFileCapability).where(SourceFileCapability.file_id == sf.id)
        ):
            db.delete(link)
        db.flush()
        ligados: set[str] = set()
        for cap in item.get("capabilities", []) or []:
            slug = str(cap.get("slug", "")).strip()
            if slug not in slugs_validos or slug in ligados:
                continue
            try:
                rel = int(cap.get("relevance", 2))
            except (TypeError, ValueError):
                rel = 2
            db.add(
                SourceFileCapability(
                    file_id=sf.id, capability_slug=slug, relevance=max(1, min(3, rel)),
                    note=(cap.get("note") or None),
                )
            )
            ligados.add(slug)
        run.candidates_created += 1

    # arquivos do lote que o agente não devolveu ficam de fora (voltam no próximo inventário)
    run.candidates_rejected += len(por_path) - len(vistos)

    existentes = {
        s.name.lower(): s
        for s in db.scalars(
            select(CapabilitySuggestion).where(
                CapabilitySuggestion.source_id == source.id,
                CapabilitySuggestion.domain_slug == domain,
            )
        )
    }
    for sug in payload.get("suggested_capabilities", []) or []:
        nome = str(sug.get("name", "")).strip()[:200]
        if not nome:
            continue
        exemplos = [str(e) for e in (sug.get("example_files") or [])][:10]
        atual = existentes.get(nome.lower())
        if atual is not None:
            atual.hits += 1
            atual.example_files = list(dict.fromkeys((atual.example_files or []) + exemplos))[:10]
            continue
        novo = CapabilitySuggestion(
            source_id=source.id, domain_slug=domain, name=nome,
            rationale=(sug.get("rationale") or None), example_files=exemplos, run_id=run.id,
        )
        db.add(novo)
        existentes[nome.lower()] = novo
        run.questions_created += 1
    db.flush()


# ---------- consulta ----------


def files_for_capability(
    db: Session, source_id: uuid.UUID, capability: str, min_relevance: int = 2
) -> list[tuple[SourceFile, int]]:
    rows = db.execute(
        select(SourceFile, SourceFileCapability.relevance)
        .join(SourceFileCapability, SourceFileCapability.file_id == SourceFile.id)
        .where(
            SourceFile.source_id == source_id,
            SourceFileCapability.capability_slug == capability,
            SourceFileCapability.relevance >= min_relevance,
        )
        .order_by(SourceFileCapability.relevance.desc(), SourceFile.path)
    ).all()
    return [(sf, rel) for sf, rel in rows]


def inventory_summary(db: Session, source_id: uuid.UUID) -> dict:
    total = db.scalar(
        select(func.count()).select_from(SourceFile).where(SourceFile.source_id == source_id)
    ) or 0
    ultimo = db.scalar(
        select(func.max(SourceFile.inventoried_at)).where(SourceFile.source_id == source_id)
    )
    por_cap = db.execute(
        select(
            SourceFileCapability.capability_slug,
            SourceFileCapability.relevance,
            func.count(),
        )
        .join(SourceFile, SourceFile.id == SourceFileCapability.file_id)
        .where(SourceFile.source_id == source_id)
        .group_by(SourceFileCapability.capability_slug, SourceFileCapability.relevance)
    ).all()
    caps: dict[str, dict] = {}
    for slug, rel, n in por_cap:
        c = caps.setdefault(slug, {"slug": slug, "files": 0, "by_relevance": {1: 0, 2: 0, 3: 0}})
        c["files"] += n
        c["by_relevance"][rel] = n
    com_cap = db.scalar(
        select(func.count(func.distinct(SourceFileCapability.file_id)))
        .join(SourceFile, SourceFile.id == SourceFileCapability.file_id)
        .where(SourceFile.source_id == source_id)
    ) or 0
    sugestoes = db.scalars(
        select(CapabilitySuggestion)
        .where(CapabilitySuggestion.source_id == source_id)
        .order_by(CapabilitySuggestion.hits.desc(), CapabilitySuggestion.name)
    ).all()
    return {
        "files": total,
        "files_with_capability": com_cap,
        "files_without_capability": total - com_cap,
        "last_inventoried_at": ultimo.isoformat() if ultimo else None,
        "capabilities": sorted(caps.values(), key=lambda c: -c["files"]),
        "suggestions": [
            {
                "id": str(s.id), "name": s.name, "rationale": s.rationale,
                "example_files": s.example_files or [], "hits": s.hits,
                "domain_slug": s.domain_slug,
            }
            for s in sugestoes
        ],
    }


def list_inventory(
    db: Session,
    source_id: uuid.UUID,
    *,
    capability: str | None = None,
    q: str | None = None,
    limit: int = 500,
) -> list[dict]:
    stmt = select(SourceFile).where(SourceFile.source_id == source_id)
    if capability:
        stmt = stmt.join(SourceFileCapability, SourceFileCapability.file_id == SourceFile.id).where(
            SourceFileCapability.capability_slug == capability
        )
    if q:
        stmt = stmt.where(SourceFile.path.ilike(f"%{q}%") | SourceFile.summary.ilike(f"%{q}%"))
    arquivos = db.scalars(stmt.order_by(SourceFile.path).limit(limit)).all()
    ids = [a.id for a in arquivos]
    links: dict[uuid.UUID, list[dict]] = {}
    if ids:
        for lk in db.scalars(
            select(SourceFileCapability).where(SourceFileCapability.file_id.in_(ids))
        ):
            links.setdefault(lk.file_id, []).append(
                {"slug": lk.capability_slug, "relevance": lk.relevance, "note": lk.note}
            )
    return [
        {
            "id": str(a.id),
            "path": a.path,
            "language": a.language,
            "lines": a.lines,
            "summary": a.summary,
            "commit": a.commit,
            "inventoried_at": a.inventoried_at.isoformat() if a.inventoried_at else None,
            "capabilities": sorted(links.get(a.id, []), key=lambda c: -c["relevance"]),
        }
        for a in arquivos
    ]
