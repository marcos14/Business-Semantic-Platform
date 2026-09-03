"""Discovery Engine (PRD §11-§12): orquestra o harness e ingere candidates.

Pipeline por run: workspace descartável → harness (saída estruturada) →
verificação mecânica de evidence contra o commit → dedup → criação via kernel
(gates de sempre) → avaliação/roteamento (§99). O agente propõe; o kernel decide.
"""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import prompts
from app.config import settings
from app.engines import claude_code, workspace
from app.kernel import events
from app.kernel.errors import KernelError, NotFoundError
from app.kernel.ir.envelope import (
    AtomKind,
    Classification,
    EvidenceRelation,
    EvidenceType,
    LifecycleStatus,
    Origin,
    RiskLevel,
)
from app.models.auth import Capability
from app.models.discovery import DiscoveryRun
from app.models.inventory import SourceFile
from app.models.knowledge import KnowledgeAtom, Source
from app.services import evaluation
from app.services import inventory as invsvc
from app.services import knowledge as ksvc

SIMILARITY_THRESHOLD = 0.85


def _capability_info(db: Session, slug: str | None) -> dict | None:
    if not slug:
        return None
    cap = db.get(Capability, slug)
    if cap is None:
        return {"slug": slug, "name": slug, "description": None}
    return {"slug": cap.slug, "name": cap.name, "description": cap.description}


def _language_notes(ws: workspace.Workspace) -> str:
    try:
        return prompts.language_notes(workspace.list_files(ws, invsvc.source_extensions()))
    except Exception:  # notas são auxiliares: nunca derrubam o run
        return ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def _statement_hash(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode()).hexdigest()


def _evidence_type(file: str, agent: str) -> EvidenceType:
    f = file.lower()
    if agent == "test" or "_test." in f or "/test" in f or f.startswith("test"):
        return EvidenceType.TEST
    return EvidenceType.SOURCE_CODE


def _verify_evidence(ws: workspace.Workspace, ev: dict) -> str | None:
    """Devolve o excerpt REAL do arquivo, ou None se a citação não existir no commit."""
    try:
        return workspace.read_lines(
            ws, str(ev["file"]), int(ev["start_line"]), int(ev["end_line"])
        )
    except (KeyError, TypeError, ValueError):
        return None


def _map_body(c: dict) -> tuple[AtomKind, dict, str | None]:
    """Mapeia o candidate do agente para (kind, body, description) do registry."""
    kind = AtomKind(c["kind"])
    statement = c["statement"]
    if kind in (AtomKind.RULE, AtomKind.INVARIANT):
        return kind, {"statement": statement}, c.get("description")
    if kind == AtomKind.DECISION:
        inputs, output = c.get("decision_inputs"), c.get("decision_output")
        if inputs and output:
            return kind, {"inputs": inputs, "output": output}, statement
        return AtomKind.RULE, {"statement": statement}, c.get("description")
    if kind == AtomKind.SCENARIO:
        return (
            kind,
            {
                "given": {"description": c.get("scenario_given") or statement},
                "when": {"description": c.get("scenario_when") or ""},
                "then": {"description": c.get("scenario_then") or ""},
            },
            statement,
        )
    # concept / state: statement vira descrição
    return kind, {}, c.get("description") or statement


def _existing_statements(db: Session, domain: str, capability: str | None) -> list[tuple[str, str]]:
    stmt = select(KnowledgeAtom).where(KnowledgeAtom.domain == domain)
    if capability:
        stmt = stmt.where(KnowledgeAtom.capability == capability)
    pares = []
    for a in db.scalars(stmt):
        texto = (a.body or {}).get("statement") or a.title
        pares.append((a.id, _normalize(texto)))
    return pares


def _finish(db: Session, run: DiscoveryRun, status: str, error: str | None = None) -> DiscoveryRun:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(UTC)
    db.commit()
    return run


def _falha_workspace(
    db: Session, *, source_id: uuid.UUID, agent: str, domain: str, capability: str | None,
    model: str, effort: str, actor: str, erro: Exception,
) -> DiscoveryRun:
    """Clone impossível (caminho errado, sem .git, branch inexistente…): registra um run
    `failed` para a falha aparecer na auditoria/tela em vez de morrer só no log do worker."""
    run = DiscoveryRun(
        source_id=source_id, agent=agent, domain=domain, capability=capability,
        model=model, effort=effort, created_by=actor,
    )
    db.add(run)
    return _finish(db, run, "failed", f"workspace: {erro}")


def run_discovery(
    db: Session,
    *,
    source_id: uuid.UUID,
    agent: str,
    domain: str,
    capability: str | None,
    actor: str,
    scope_hint: str = "todo o repositório",
    max_candidates: int = 40,
    budget_usd: float | None = 5.0,
    model: str = "opus",
    effort: str = "high",
    timeout_min: int = 30,
    executable: str = "claude",
) -> DiscoveryRun:
    if agent not in ("code", "test"):
        raise KernelError(f"Agent de discovery desconhecido: {agent}")
    source = db.get(Source, source_id)
    if source is None or not source.repository:
        raise NotFoundError("Source inexistente ou sem repositório")

    try:
        ws = workspace.acquire(source.repository, source.branch, source.commit)
    except RuntimeError as e:
        return _falha_workspace(
            db, source_id=source_id, agent=agent, domain=domain, capability=capability,
            model=model, effort=effort, actor=actor, erro=e,
        )
    try:
        ctx = dict(
            domain=domain,
            capability=_capability_info(db, capability),
            languages=_language_notes(ws),
        )
        prompt = (
            prompts.code_discovery_prompt(scope_hint, max_candidates, **ctx)
            if agent == "code"
            else prompts.test_discovery_prompt(scope_hint, max_candidates, **ctx)
        )
        p_hash = claude_code.prompt_hash(prompt, prompts.DISCOVERY_SCHEMA)

        # Idempotência: mesmo (source, commit, agent, prompt) já sucedido → não repete
        existente = db.scalar(
            select(DiscoveryRun).where(
                DiscoveryRun.source_id == source_id,
                DiscoveryRun.commit == ws.commit,
                DiscoveryRun.agent == agent,
                DiscoveryRun.prompt_hash == p_hash,
                DiscoveryRun.status == "succeeded",
            )
        )
        if existente:
            return existente

        run = DiscoveryRun(
            source_id=source_id, agent=agent, domain=domain, capability=capability,
            commit=ws.commit, model=model, effort=effort, prompt_hash=p_hash,
            created_by=actor,
        )
        db.add(run)
        db.commit()  # run visível/auditável desde o início

        res = claude_code.run(
            claude_code.RunOptions(
                workdir=ws.path,
                prompt=prompt,
                schema=prompts.DISCOVERY_SCHEMA,
                logs_dir=Path(settings.discovery_logs_dir),
                label=f"{agent}-discovery-{str(run.id)[:8]}",
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
            return _finish(
                db, run, "failed",
                f"{res.subtype or 'erro'}: {res.result_text[:800]}",
            )

        _ingest(db, run, source, ws, res.structured, agent=agent, model=model)
        return _finish(db, run, "succeeded")
    finally:
        workspace.destroy(ws)


def _ingest(
    db: Session,
    run: DiscoveryRun,
    source: Source,
    ws: workspace.Workspace,
    payload: dict,
    *,
    agent: str,
    model: str,
) -> None:
    actor = f"agent:{agent}-discovery:{model}"
    existentes = _existing_statements(db, run.domain, run.capability)
    hashes = {h for _, h in ((i, _statement_hash(t)) for i, t in existentes)}

    for c in payload.get("candidates", []):
        try:
            kind, body, description = _map_body(c)
        except (KeyError, ValueError):
            run.candidates_rejected += 1
            continue

        # Verificação mecânica de evidence contra o commit (anti-alucinação)
        evidencias = []
        for ev in c.get("evidence", []):
            excerpt = _verify_evidence(ws, ev)
            if excerpt is None:
                run.evidence_rejected += 1
                continue
            evidencias.append(
                {
                    "type": _evidence_type(str(ev["file"]), agent),
                    "source_id": source.id,
                    "location": {
                        "file": ev["file"],
                        "start_line": ev["start_line"],
                        "end_line": ev["end_line"],
                        "repository": source.repository,
                        "commit": ws.commit,
                    },
                    "summary": ev.get("summary"),
                    "excerpt": excerpt,
                }
            )
        if not evidencias:
            run.candidates_rejected += 1
            continue

        statement = c["statement"]
        norm = _normalize(statement)
        if _statement_hash(statement) in hashes:
            run.duplicates_skipped += 1
            continue
        similar = next(
            (
                aid
                for aid, texto in existentes
                if SequenceMatcher(None, norm, texto).ratio() >= SIMILARITY_THRESHOLD
            ),
            None,
        )

        try:
            atom = ksvc.create_candidate(
                db,
                actor=actor,
                origin=Origin.AGENT,
                kind=kind,
                title=c["title"][:300],
                domain=run.domain,
                capability=run.capability,
                description=description,
                classification=Classification(c["classification"]),
                risk=RiskLevel(c["risk"]) if c.get("risk") else None,
                body=body,
                evidence=evidencias,
            )
        except KernelError:
            run.candidates_rejected += 1
            continue
        db.flush()
        run.candidates_created += 1
        existentes.append((atom.id, norm))
        hashes.add(_statement_hash(statement))

        if similar:
            # §12: Potential Duplicate é conhecimento — registrado, nunca merge (P7)
            run.potential_duplicates += 1
            events.record_event(
                db, events.POTENTIAL_DUPLICATE, actor, atom.id,
                {"similar_to": similar, "threshold": SIMILARITY_THRESHOLD},
            )

        evaluation.evaluate_atom(db, atom.id, trigger=f"discovery:{run.id}")

    for q in payload.get("questions", []):
        if not q.get("question"):
            continue
        try:
            ksvc.create_candidate(
                db,
                actor=actor,
                origin=Origin.AGENT,
                kind=AtomKind.QUESTION,
                title=q["question"][:300],
                domain=run.domain,
                capability=run.capability,
                description=q.get("context"),
                body={"question": q["question"]},
            )
            run.questions_created += 1
        except KernelError:
            run.candidates_rejected += 1


# ---------- Discovery dirigido: um turno por arquivo (ou faixa) por capability ----------


def _chunks(total_lines: int, chunk_lines: int) -> list[tuple[int, int]]:
    total = max(total_lines, 1)
    if total <= chunk_lines:
        return [(1, total)]
    faixas = []
    inicio = 1
    while inicio <= total:
        fim = min(inicio + chunk_lines - 1, total)
        faixas.append((inicio, fim))
        inicio = fim + 1
    return faixas


def plan_directed(
    db: Session,
    source: Source,
    *,
    capability: str,
    min_relevance: int = 2,
    max_files: int | None = None,
    chunk_lines: int | None = None,
) -> list[dict]:
    """Turnos de uma campanha: [{file, start_line, end_line, total_lines, relevance}].
    Arquivos maiores que `chunk_lines` viram vários turnos (faixas contíguas)."""
    chunk_lines = chunk_lines or settings.discovery_chunk_lines
    arquivos = invsvc.files_for_capability(db, source.id, capability, min_relevance)
    if max_files:
        arquivos = arquivos[:max_files]
    plano = []
    for sf, rel in arquivos:
        for ini, fim in _chunks(sf.lines, chunk_lines):
            plano.append(
                {"file": sf.path, "start_line": ini, "end_line": fim,
                 "total_lines": sf.lines, "relevance": rel}
            )
    return plano


def _followups_validos(
    ws: workspace.Workspace, alvo: str, followups: list[dict], chunk_lines: int
) -> list[dict]:
    """Só arquivos que existem no workspace e não são o alvo; já fatiados em faixas."""
    saida = []
    vistos = {alvo}
    for f in followups or []:
        path = str(f.get("file", "")).replace("\\", "/").strip().lstrip("./")
        if not path or path in vistos:
            continue
        try:
            _, total, _ = workspace.read_text(ws, path, max_chars=1)
        except (OSError, ValueError):
            continue
        vistos.add(path)
        for ini, fim in _chunks(total, chunk_lines):
            saida.append(
                {"file": path, "start_line": ini, "end_line": fim, "total_lines": total,
                 "reason": str(f.get("reason", ""))[:300]}
            )
    return saida


def run_directed_discovery(
    db: Session,
    *,
    source_id: uuid.UUID,
    domain: str,
    capability: str,
    file: str,
    start_line: int = 1,
    end_line: int | None = None,
    actor: str,
    batch_id: uuid.UUID | None = None,
    is_followup: bool = False,
    budget_usd: float | None = 3.0,
    max_candidates: int = 12,
    model: str = "opus",
    effort: str = "high",
    timeout_min: int = 20,
    executable: str = "claude",
) -> DiscoveryRun:
    """Um arquivo (ou faixa de linhas) × uma capability = um run do harness com o conteúdo
    NUMERADO embutido no prompt. Follow-ups pedidos pelo agente voltam em `run.followups`
    (lista já validada contra o workspace) para o chamador enfileirar."""
    source = db.get(Source, source_id)
    if source is None or not source.repository:
        raise NotFoundError("Source inexistente ou sem repositório")
    cap_info = _capability_info(db, capability)
    file = file.replace("\\", "/")
    prefixo = "f:" if is_followup else ""

    run = DiscoveryRun(
        source_id=source_id, agent="code", domain=domain, capability=capability,
        model=model, effort=effort, created_by=actor, batch_id=batch_id, target_file=file,
    )
    run.followups = []  # atributo transiente (não persistido)
    try:
        ws = workspace.acquire(source.repository, source.branch, source.commit)
    except RuntimeError as e:
        db.add(run)
        return _finish(db, run, "failed", f"workspace: {e}")

    try:
        try:
            texto, total, _ = workspace.read_text(ws, file)
        except (OSError, ValueError) as e:
            db.add(run)
            return _finish(db, run, "failed", f"arquivo alvo ilegível: {file} ({e})")
        linhas = texto.splitlines()
        total = max(len(linhas), 1)
        fim = min(end_line or total, total)
        ini = max(1, min(start_line, fim))
        conteudo = "\n".join(linhas[ini - 1 : fim])
        run.line_range = f"{prefixo}{ini}-{fim}"

        sf = db.scalar(
            select(SourceFile).where(SourceFile.source_id == source_id, SourceFile.path == file)
        )
        relacionados = [
            {"path": s.path, "summary": s.summary}
            for s, _ in invsvc.files_for_capability(db, source_id, capability, 2)
            if s.path != file
        ][:12]

        prompt = prompts.directed_discovery_prompt(
            domain=domain, capability=cap_info or {"slug": capability, "name": capability},
            file=file, content=conteudo, start_line=ini, end_line=fim, total_lines=total,
            max_candidates=max_candidates, file_summary=sf.summary if sf else None,
            related_files=relacionados,
        )
        p_hash = claude_code.prompt_hash(prompt, prompts.DIRECTED_SCHEMA)

        existente = db.scalar(
            select(DiscoveryRun).where(
                DiscoveryRun.source_id == source_id,
                DiscoveryRun.commit == ws.commit,
                DiscoveryRun.agent == "code",
                DiscoveryRun.prompt_hash == p_hash,
                DiscoveryRun.status == "succeeded",
            )
        )
        if existente:
            existente.followups = []
            return existente

        run.commit = ws.commit
        run.prompt_hash = p_hash
        db.add(run)
        db.commit()

        res = claude_code.run(
            claude_code.RunOptions(
                workdir=ws.path,
                prompt=prompt,
                schema=prompts.DIRECTED_SCHEMA,
                logs_dir=Path(settings.discovery_logs_dir),
                label=f"directed-{capability}-{str(run.id)[:8]}",
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
            return _finish(
                db, run, "failed", f"{res.subtype or 'erro'}: {res.result_text[:800]}"
            )

        _ingest(db, run, source, ws, res.structured, agent="code", model=model)
        run.followups = _followups_validos(
            ws, file, res.structured.get("followups", []), settings.discovery_chunk_lines
        )
        return _finish(db, run, "succeeded")
    finally:
        workspace.destroy(ws)


def _reopen_routing_if_unreviewed(db: Session, atom_id: str, *, run_id: str) -> None:
    """Corroboração reabre o roteamento automático — mas NUNCA por cima de humanos:
    só quando o atom está em NEEDS_HUMAN_REVIEW sem nenhum voto registrado."""
    from app.models.review import Vote

    atom = ksvc.get_atom(db, atom_id)
    if atom.status != str(LifecycleStatus.NEEDS_HUMAN_REVIEW):
        return
    tem_voto = db.scalar(select(Vote).where(Vote.atom_id == atom_id))
    if tem_voto is not None:
        return
    ksvc.change_status(
        db,
        atom_id,
        actor="system:corroboration",
        new_status=LifecycleStatus.CORROBORATING,
        reason=f"nova evidência de corroboração (run {run_id})",
        expected_lock_version=atom.lock_version,
    )


def run_corroboration(
    db: Session,
    *,
    source_id: uuid.UUID,
    domain: str,
    capability: str | None,
    actor: str,
    max_atoms: int = 30,
    budget_usd: float | None = 5.0,
    model: str = "opus",
    effort: str = "high",
    timeout_min: int = 30,
    executable: str = "claude",
) -> DiscoveryRun:
    """Corroboration Agent (§88): segundo agente busca evidência independente."""
    source = db.get(Source, source_id)
    if source is None or not source.repository:
        raise NotFoundError("Source inexistente ou sem repositório")

    alvo_status = {
        str(LifecycleStatus.CANDIDATE),
        str(LifecycleStatus.CORROBORATING),
        str(LifecycleStatus.NEEDS_HUMAN_REVIEW),
        str(LifecycleStatus.IN_REVIEW),
    }
    stmt = select(KnowledgeAtom).where(
        KnowledgeAtom.domain == domain,
        KnowledgeAtom.origin == str(Origin.AGENT),
        KnowledgeAtom.status.in_(alvo_status),
        KnowledgeAtom.kind.in_(["rule", "invariant", "scenario", "decision"]),
    )
    if capability:
        stmt = stmt.where(KnowledgeAtom.capability == capability)
    atoms = list(db.scalars(stmt.limit(max_atoms)))
    if not atoms:
        raise KernelError("Nenhum candidate elegível para corroboração")

    alvos = [
        {"atom_id": a.id, "statement": (a.body or {}).get("statement") or a.title}
        for a in atoms
    ]
    try:
        ws = workspace.acquire(source.repository, source.branch, source.commit)
    except RuntimeError as e:
        return _falha_workspace(
            db, source_id=source_id, agent="corroboration", domain=domain,
            capability=capability, model=model, effort=effort, actor=actor, erro=e,
        )
    try:
        prompt = prompts.corroboration_prompt(
            alvos,
            domain=domain,
            capability=_capability_info(db, capability),
            languages=_language_notes(ws),
        )
        run = DiscoveryRun(
            source_id=source_id, agent="corroboration", domain=domain,
            capability=capability, commit=ws.commit, model=model, effort=effort,
            prompt_hash=claude_code.prompt_hash(prompt, prompts.CORROBORATION_SCHEMA),
            created_by=actor,
        )
        db.add(run)
        db.commit()

        res = claude_code.run(
            claude_code.RunOptions(
                workdir=ws.path,
                prompt=prompt,
                schema=prompts.CORROBORATION_SCHEMA,
                logs_dir=Path(settings.discovery_logs_dir),
                label=f"corroboration-{str(run.id)[:8]}",
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
            return _finish(db, run, "failed", f"{res.subtype}: {res.result_text[:800]}")

        agent_actor = f"agent:corroboration:{model}"
        ids_validos = {a.id for a in atoms}
        for finding in res.structured.get("findings", []):
            atom_id = finding.get("atom_id")
            if atom_id not in ids_validos or finding.get("verdict") == "NOT_FOUND":
                continue
            relation = (
                EvidenceRelation.CONTRADICTS
                if finding["verdict"] == "CONTRADICTS"
                else EvidenceRelation.SUPPORTS
            )
            adicionou = False
            for ev in finding.get("evidence", []):
                excerpt = _verify_evidence(ws, ev)
                if excerpt is None:
                    run.evidence_rejected += 1
                    continue
                ksvc.add_evidence(
                    db, atom_id, actor=agent_actor, origin=Origin.AGENT,
                    type=_evidence_type(str(ev["file"]), "code"),
                    relation=relation,
                    source_id=source.id,
                    location={
                        "file": ev["file"],
                        "start_line": ev["start_line"],
                        "end_line": ev["end_line"],
                        "repository": source.repository,
                        "commit": ws.commit,
                    },
                    summary=ev.get("summary"),
                    excerpt=excerpt,
                )
                adicionou = True
            if adicionou:
                _reopen_routing_if_unreviewed(db, atom_id, run_id=str(run.id))
                evaluation.evaluate_atom(db, atom_id, trigger=f"corroboration:{run.id}")
        return _finish(db, run, "succeeded")
    finally:
        workspace.destroy(ws)
