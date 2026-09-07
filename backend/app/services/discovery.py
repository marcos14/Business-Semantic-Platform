"""Discovery Engine (PRD §11-§12): orquestra o harness e ingere candidates.

Pipeline por run: workspace descartável → harness (saída estruturada) →
verificação mecânica de evidence contra o commit → dedup → criação via kernel
(gates de sempre) → avaliação/roteamento (§99). O agente propõe; o kernel decide.

Busca de evidência (cascata, estágio 1 — mesma fonte): `run_evidence_search` corrobora em
lotes os atoms que ainda não chegaram à faixa alvo, priorizando relevância/risco, pedindo
evidência em OUTROS sítios (arquivos/rotinas ainda não citados) e exigindo mesmo escopo —
regra parecida em outro processo vira variante, nunca suporte nem conflito.
"""

import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import prompts
from app.config import settings
from app.engines import claude_code, symbols, workspace
from app.kernel import events
from app.kernel.errors import KernelError, NotFoundError
from app.kernel.ir.envelope import (
    AtomKind,
    Classification,
    EvidenceRelation,
    EvidenceType,
    LifecycleStatus,
    Origin,
    RelationType,
    RiskLevel,
    Significance,
    SourceType,
)
from app.models.auth import Capability
from app.models.discovery import DiscoveryRun
from app.models.inventory import SourceFile
from app.models.knowledge import DomainEvent, Evidence, EvidenceLink, KnowledgeAtom, Source
from app.services import embeddings as embsvc
from app.services import evaluation
from app.services import inventory as invsvc
from app.services import knowledge as ksvc

SIMILARITY_THRESHOLD = 0.85
log = logging.getLogger(__name__)

# Status em que um atom de negócio ainda pode ganhar evidência automática
EVIDENCE_TARGET_STATUSES = {
    str(LifecycleStatus.CANDIDATE),
    str(LifecycleStatus.CORROBORATING),
    str(LifecycleStatus.NEEDS_HUMAN_REVIEW),
    str(LifecycleStatus.IN_REVIEW),
    str(LifecycleStatus.PROVISIONAL),
}
CORROBORATION_KINDS = [
    "rule",
    "invariant",
    "scenario",
    "decision",
    "process",
    "transition",
    "event",
    "exception",
    "message",
    "procedure",
]
_SIGNIFICANCE_RANK = {"HIGH": 0, "MEDIUM": 1, None: 2, "LOW": 3, "SYSTEMIC": 4}
_RISK_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, None: 3, "LOW": 4}


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


def _evidence_type(file: str, agent: str, source: Source | None = None) -> EvidenceType:
    """Tipo de evidência pelo TIPO DA SOURCE (documentação, banco...) e, para código, pela
    convenção de testes."""
    stype = (source.type if source is not None else "") or ""
    if stype == SourceType.DOCUMENTATION:
        return EvidenceType.DOCUMENT
    if stype == SourceType.DATABASE_SCHEMA:
        return EvidenceType.DATABASE
    if stype == SourceType.AUTOMATED_TEST:
        return EvidenceType.TEST
    if stype == SourceType.CONFIGURATION:
        return EvidenceType.CONFIGURATION
    if stype == SourceType.API:
        return EvidenceType.API
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


def _file_lines(ws: workspace.Workspace, file: str) -> list[str]:
    try:
        texto, _, _ = workspace.read_text(ws, file)
    except (OSError, ValueError):
        return []
    return texto.splitlines()


def _build_evidence(
    ws: workspace.Workspace, source: Source, ev: dict, *, agent: str
) -> dict | None:
    """Evidence verificada: excerpt real + rotina envolvente (símbolo) verificada/inferida +
    mecanismo (informado pelo agente ou inferido do trecho). None = citação inválida."""
    excerpt = _verify_evidence(ws, ev)
    if excerpt is None:
        return None
    file = str(ev["file"])
    start, end = int(ev["start_line"]), int(ev["end_line"])
    simbolo = symbols.verify_symbol(_file_lines(ws, file), start, file, ev.get("symbol"))
    mecanismo = symbols.normalize_mechanism(ev.get("mechanism"), excerpt)
    location = {
        "file": file,
        "start_line": start,
        "end_line": end,
        "repository": source.repository,
        "commit": ws.commit,
    }
    if simbolo:
        location["symbol"] = simbolo
    return {
        "type": _evidence_type(file, agent, source),
        "source_id": source.id,
        "location": location,
        "summary": ev.get("summary"),
        "excerpt": excerpt,
        "metadata": {"mechanism": mecanismo} if mecanismo else None,
    }


def _map_body(c: dict) -> tuple[AtomKind, dict, str | None]:
    """Mapeia o candidate do agente para (kind, body, description) do registry."""
    kind = AtomKind(c["kind"])
    statement = c["statement"]
    if c.get("body"):
        return kind, c["body"], c.get("description") or statement
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
        texto = embsvc.atom_text(a)
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


# ---------- sítios já citados (para reforço e para a corroboração pedir OUTROS) ----------


def _atom_evidence(db: Session, atom_id: str) -> list[Evidence]:
    return list(
        db.scalars(
            select(Evidence)
            .join(EvidenceLink, EvidenceLink.evidence_id == Evidence.id)
            .where(EvidenceLink.atom_id == atom_id)
        )
    )


def _same_site(loc_a: dict, loc_b: dict) -> bool:
    if not loc_a.get("file") or loc_a.get("file") != loc_b.get("file"):
        return False
    sa, sb = loc_a.get("symbol"), loc_b.get("symbol")
    if sa and sb:
        return sa.lower() == sb.lower()
    try:
        a1, a2 = int(loc_a["start_line"]), int(loc_a["end_line"])
        b1, b2 = int(loc_b["start_line"]), int(loc_b["end_line"])
    except (KeyError, TypeError, ValueError):
        return True  # mesmo arquivo sem como distinguir: conservador
    return a1 <= b2 + 1 and b1 <= a2 + 1


def _is_new_site(existentes: list[Evidence], ev: dict) -> bool:
    loc = ev.get("location") or {}
    return not any(_same_site(e.location or {}, loc) for e in existentes)


def _reinforce(
    db: Session, run: DiscoveryRun, atom: KnowledgeAtom, evidencias: list[dict], *,
    actor: str, reason: str,
) -> int:
    """Anexa ao atom existente as evidências que são sítios NOVOS; devolve quantas."""
    existentes = _atom_evidence(db, atom.id)
    novas = 0
    for ev in evidencias:
        if not _is_new_site(existentes, ev):
            continue
        try:
            e = ksvc.add_evidence(
                db, atom.id, actor=actor, origin=Origin.AGENT,
                relation=EvidenceRelation.SUPPORTS, **ev,
            )
        except KernelError:
            run.evidence_rejected += 1
            continue
        existentes.append(e)
        novas += 1
        run.reinforcements += 1
    if novas:
        events.record_event(
            db, events.EVIDENCE_ADDED, actor, atom.id,
            {"reinforcement": True, "reason": reason, "run_id": str(run.id), "count": novas},
        )
        _reopen_routing_if_unreviewed(db, atom.id, run_id=str(run.id))
        evaluation.evaluate_atom(db, atom.id, trigger=f"discovery:{run.id}")
    return novas


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
    model: str | None = None,  # padrão: settings.harness_model
    effort: str | None = None,  # padrão: settings.harness_effort
    timeout_min: int = 30,
    executable: str = "claude",
) -> DiscoveryRun:
    if agent not in ("code", "test"):
        raise KernelError(f"Agent de discovery desconhecido: {agent}")
    model = model or settings.harness_model
    effort = effort or settings.harness_effort
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
    por_hash: dict[str, str] = {_statement_hash(t): aid for aid, t in existentes}

    candidatos = list(payload.get("candidates", []))
    created_by_index: dict[int, str] = {}
    created_by_local_id: dict[str, str] = {}
    # Um único lote de embeddings para todos os candidates do run (dedup semântica +
    # armazenamento). None = embeddings desligados → dedup textual de sempre.
    textos = [f"{c.get('title', '')}. {c.get('statement', '')}".strip() for c in candidatos]
    vetores = embsvc.embed_texts(textos) if candidatos else None

    for i, c in enumerate(candidatos):
        try:
            kind, body, description = _map_body(c)
        except (KeyError, ValueError):
            run.candidates_rejected += 1
            continue

        # Régua de relevância (regra 8 do prompt). Sem marcação = MEDIUM (fluxo normal).
        # "TRIVIAL" (nome antigo) é lido como SYSTEMIC: comportamento objetivo, gravado e
        # aprovado sem humano — o roteamento decide, não a ingestão.
        significance = str(c.get("significance") or Significance.MEDIUM).upper()
        if significance == "TRIVIAL":
            significance = str(Significance.SYSTEMIC)
        if significance not in Significance.__members__:
            significance = str(Significance.MEDIUM)

        # Verificação mecânica de evidence contra o commit (anti-alucinação)
        evidencias = []
        for ev in c.get("evidence", []):
            construida = _build_evidence(ws, source, ev, agent=agent)
            if construida is None:
                run.evidence_rejected += 1
                continue
            evidencias.append(construida)
        if not evidencias:
            run.candidates_rejected += 1
            continue

        statement = c["statement"]
        norm = _normalize(statement)
        h = _statement_hash(statement)
        if h in por_hash:
            # Duplicata exata: a evidência NÃO é jogada fora — se cita outro sítio, reforça
            # o atom existente (corroboração que a campanha já pagou).
            run.duplicates_skipped += 1
            alvo = db.get(KnowledgeAtom, por_hash[h])
            created_by_index[i] = por_hash[h]
            if c.get("local_id"):
                created_by_local_id[str(c["local_id"])] = por_hash[h]
            if alvo is not None and alvo.kind in embsvc.BUSINESS_KINDS:
                _reinforce(db, run, alvo, evidencias, actor=actor, reason="duplicata exata")
            continue
        similar: str | None = None
        similaridade: float | None = None
        metodo = "text"
        if vetores is not None:
            # dedup semântica: o mais próximo no domain decide entre pular, marcar ou criar
            proximos = embsvc.similar_atoms(db, vetores[i], domain=run.domain, k=1)
            if proximos:
                cand, sim = proximos[0]
                metodo = "embedding"
                if sim >= settings.dedup_skip_similarity:
                    run.duplicates_skipped += 1
                    _reinforce(
                        db, run, cand, evidencias, actor=actor,
                        reason=f"duplicata semântica ({sim:.2f})",
                    )
                    created_by_index[i] = cand.id
                    if c.get("local_id"):
                        created_by_local_id[str(c["local_id"])] = cand.id
                    continue
                if sim >= settings.dedup_flag_similarity:
                    similar, similaridade = cand.id, round(sim, 4)
        else:
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
                scope=c.get("scope"),
                effective=c.get("effective"),
                body=body,
                evidence=evidencias,
                significance=significance,
            )
        except KernelError:
            run.candidates_rejected += 1
            continue
        db.flush()
        created_by_index[i] = atom.id
        if c.get("local_id"):
            created_by_local_id[str(c["local_id"])] = atom.id
        run.candidates_created += 1
        if significance == Significance.SYSTEMIC:
            run.systemic_created += 1
        existentes.append((atom.id, norm))
        por_hash[h] = atom.id
        if vetores is not None:
            embsvc.store_embedding(db, atom.id, textos[i], vetores[i])

        if similar:
            # §12: Potential Duplicate é conhecimento — registrado, nunca merge (P7)
            run.potential_duplicates += 1
            events.record_event(
                db, events.POTENTIAL_DUPLICATE, actor, atom.id,
                {
                    "similar_to": similar,
                    "method": metodo,
                    "similarity": similaridade,
                    "threshold": settings.dedup_flag_similarity
                    if metodo == "embedding" else SIMILARITY_THRESHOLD,
                },
            )

        evaluation.evaluate_atom(db, atom.id, trigger=f"discovery:{run.id}")

    # Linking explícito do agente. IDs só são aceitos quando existem; referências locais
    # resolvem candidates efetivamente criados ou deduplicados neste mesmo run.
    for i, candidate in enumerate(candidatos):
        from_atom = created_by_index.get(i)
        if not from_atom:
            continue
        relation_added = False
        for raw_relation in candidate.get("relations", []) or []:
            to_atom = raw_relation.get("to_atom") or created_by_local_id.get(
                str(raw_relation.get("to_local_id") or "")
            )
            if not to_atom or db.get(KnowledgeAtom, to_atom) is None:
                continue
            try:
                ksvc.add_relation(
                    db,
                    actor=actor,
                    from_atom=from_atom,
                    to_atom=to_atom,
                    relation_type=RelationType(raw_relation["type"]),
                )
                relation_added = True
            except (KernelError, KeyError, ValueError):
                continue
        if relation_added:
            evaluation.evaluate_atom(db, from_atom, trigger=f"discovery-linking:{run.id}")

    # Reforços (discovery dirigido): o agente reconheceu conhecimento já registrado e cita
    # este arquivo como evidência adicional — sítio novo, em vez de duplicata.
    for r in payload.get("reinforcements", []) or []:
        atom_id = str(r.get("atom_id", "")).strip()
        alvo = db.get(KnowledgeAtom, atom_id) if atom_id else None
        if alvo is None or alvo.domain != run.domain or alvo.kind not in embsvc.BUSINESS_KINDS:
            run.candidates_rejected += 1
            continue
        evidencias = []
        for ev in r.get("evidence", []) or []:
            construida = _build_evidence(ws, source, ev, agent=agent)
            if construida is None:
                run.evidence_rejected += 1
                continue
            if not construida.get("summary"):
                construida["summary"] = r.get("note")
            evidencias.append(construida)
        if evidencias:
            _reinforce(db, run, alvo, evidencias, actor=actor, reason="reforço do agente")

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
    model: str | None = None,  # padrão: settings.harness_model
    effort: str | None = None,  # padrão: settings.harness_effort
    timeout_min: int = 20,
    executable: str = "claude",
) -> DiscoveryRun:
    """Um arquivo (ou faixa de linhas) × uma capability = um run do harness com o conteúdo
    NUMERADO embutido no prompt. Follow-ups pedidos pelo agente voltam em `run.followups`
    (lista já validada contra o workspace) para o chamador enfileirar."""
    source = db.get(Source, source_id)
    if source is None or not source.repository:
        raise NotFoundError("Source inexistente ou sem repositório")
    model = model or settings.harness_model
    effort = effort or settings.harness_effort
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

        # Recuperação vetorial: os candidates já registrados mais próximos deste arquivo
        # entram no prompt (poucos tokens) para o agente reforçar em vez de duplicar.
        existing: list[dict] = []
        try:
            embsvc.ensure_atom_embeddings(db, domain=domain)
            consulta = " ".join(
                p for p in (
                    (cap_info or {}).get("name") or capability,
                    (cap_info or {}).get("description") or "",
                    (sf.summary if sf and sf.summary else file),
                ) if p
            )
            qv = embsvc.embed_texts([consulta])
            if qv:
                existing = [
                    {
                        "atom_id": a.id, "title": a.title, "status": a.status,
                        "statement": ((a.body or {}).get("statement") or a.description or "")[:300],
                    }
                    for a, _sim in embsvc.similar_atoms(
                        db, qv[0], domain=domain, capability=capability
                    )
                ]
        except Exception:  # recuperação é auxiliar: nunca derruba o run
            log.warning("recuperação vetorial indisponível neste turno", exc_info=True)
            existing = []

        base_prompt = dict(
            domain=domain, capability=cap_info or {"slug": capability, "name": capability},
            file=file, content=conteudo, start_line=ini, end_line=fim, total_lines=total,
            max_candidates=max_candidates, file_summary=sf.summary if sf else None,
            related_files=relacionados,
        )
        prompt = prompts.directed_discovery_prompt(**base_prompt, existing=existing)
        # Idempotência pelo prompt ESTÁVEL (sem o bloco de conhecimento recuperado, que muda
        # a cada candidate novo): mesmo arquivo/faixa/commit já sucedido não roda de novo.
        p_hash = claude_code.prompt_hash(
            prompts.directed_discovery_prompt(**base_prompt, existing=None),
            prompts.DIRECTED_SCHEMA,
        )

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


# ---------- Corroboração / busca de evidência (cascata, estágio 1: mesma fonte) ----------

_SQL_TABLE = re.compile(r"\b(?:from|join|into|update)\s+([A-Za-z_][\w.]*)", re.I)
_DELPHI_CLASS = re.compile(r"\bT[A-Z][A-Za-z0-9]{2,}\b")
_DATASET = re.compile(
    r"\b([A-Za-z_]\w*)\.(?:FieldByName|ParamByName|Params|Open|Post|Edit|Append|Insert)\b"
)
_GENERIC_ANCHORS = {
    "tobject", "tform", "tcomponent", "tstringlist", "tdataset", "tquery", "tstrings",
    "tbutton", "tedit", "tlabel", "tpanel", "tlist", "texception", "tdatetime", "tclass",
    "self", "sender", "result", "dual", "sysdate", "select", "table",
}


def anchors_of(text: str | None) -> set[str]:
    """Âncoras de escopo de um trecho: tabelas em SQL, classes/forms Delphi, datasets."""
    if not text:
        return set()
    achados: set[str] = set()
    for pat in (_SQL_TABLE, _DELPHI_CLASS, _DATASET):
        for m in pat.finditer(text):
            token = (m.group(1) if pat.groups else m.group(0)).strip().lower()
            if token and token not in _GENERIC_ANCHORS and len(token) > 2:
                achados.add(token)
    return achados


def _atom_anchors(evidencias: list[Evidence]) -> set[str]:
    saida: set[str] = set()
    for e in evidencias:
        saida |= anchors_of(e.excerpt)
    return saida


def _already_searched(
    db: Session, atom_ids: list[str], source_id: uuid.UUID, commit: str
) -> set[str]:
    if not atom_ids:
        return set()
    return set(
        db.scalars(
            select(DomainEvent.atom_id).where(
                DomainEvent.event_type == events.EVIDENCE_SEARCHED,
                DomainEvent.atom_id.in_(atom_ids),
                DomainEvent.payload["source_id"].astext == str(source_id),
                DomainEvent.payload["commit"].astext == commit,
            )
        )
    )


def select_evidence_targets(
    db: Session,
    *,
    source: Source,
    domain: str,
    capability: str | None,
    commit: str | None,
    max_atoms: int = 30,
) -> list[KnowledgeAtom]:
    """Atoms de negócio que ainda podem ganhar evidência, na ordem de quem mais precisa:
    relevância (HIGH primeiro), risco, menor confiança, mais antigo. Exclui os já buscados
    nesta source/commit (evento EvidenceSearched) para nunca perguntar duas vezes."""
    stmt = select(KnowledgeAtom).where(
        KnowledgeAtom.domain == domain,
        KnowledgeAtom.origin == str(Origin.AGENT),
        KnowledgeAtom.status.in_(EVIDENCE_TARGET_STATUSES),
        KnowledgeAtom.kind.in_(CORROBORATION_KINDS),
    )
    if capability:
        stmt = stmt.where(KnowledgeAtom.capability == capability)
    atoms = list(db.scalars(stmt))
    if commit:
        ja = _already_searched(db, [a.id for a in atoms], source.id, commit)
        atoms = [a for a in atoms if a.id not in ja]
    atoms.sort(
        key=lambda a: (
            _SIGNIFICANCE_RANK.get(a.significance, 2),
            _RISK_RANK.get(a.risk, 3),
            a.confidence if a.confidence is not None else 0.0,
            a.created_at,
        )
    )
    return atoms[:max_atoms]


def _variant(
    db: Session, run: DiscoveryRun, source: Source, ws: workspace.Workspace, atom: KnowledgeAtom,
    finding: dict, evidencias: list[dict], *, actor: str, reason: str,
) -> None:
    """Regra parecida em OUTRO escopo: nunca vira suporte nem conflito. Vira candidate
    irmão ligado por VARIANT_OF (quando o agente enunciou a regra) e uma question de baixa
    prioridade para um humano dizer se são a mesma regra ou processos distintos."""
    nota = str(finding.get("note") or "").strip()
    variante_stmt = str(finding.get("variant_statement") or "").strip()
    novo_id: str | None = None
    if variante_stmt and evidencias:
        try:
            novo = ksvc.create_candidate(
                db, actor=actor, origin=Origin.AGENT, kind=AtomKind.RULE,
                title=str(finding.get("variant_title") or variante_stmt)[:300],
                domain=atom.domain, capability=atom.capability,
                description=nota or None,
                classification=Classification.OBSERVED_BEHAVIOR,
                risk=RiskLevel(atom.risk) if atom.risk else None,
                body={"statement": variante_stmt},
                evidence=evidencias,
                significance=atom.significance,
            )
            db.flush()
            novo_id = novo.id
            run.candidates_created += 1
            try:
                ksvc.add_relation(
                    db, actor=actor, from_atom=novo.id, to_atom=atom.id,
                    relation_type=RelationType.VARIANT_OF,
                )
            except KernelError:
                pass
            evaluation.evaluate_atom(db, novo.id, trigger=f"corroboration:{run.id}")
        except KernelError:
            run.candidates_rejected += 1
    pergunta = (
        f"Regra parecida em outro escopo: \"{atom.title}\" também aparece em "
        f"{', '.join(sorted({e['location']['file'] for e in evidencias})) or 'outro processo'}"
        f"{' (' + nota + ')' if nota else ''}. É a mesma regra ou são processos distintos?"
    )
    try:
        ksvc.create_candidate(
            db, actor=actor, origin=Origin.AGENT, kind=AtomKind.QUESTION,
            title=pergunta[:300], domain=atom.domain, capability=atom.capability,
            description=(nota or None) if not novo_id else f"Candidate irmão: {novo_id}",
            body={"question": pergunta},
            evidence=evidencias if not novo_id else [],
        )
        run.questions_created += 1
    except KernelError:
        run.candidates_rejected += 1
    events.record_event(
        db, events.VARIANT_DETECTED, actor, atom.id,
        {"variant_atom": novo_id, "reason": reason, "run_id": str(run.id), "note": nota},
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
    model: str | None = None,  # padrão: settings.harness_corroboration_model
    effort: str | None = None,  # padrão: settings.harness_effort
    timeout_min: int = 30,
    executable: str = "claude",
    atoms: list[KnowledgeAtom] | None = None,
) -> DiscoveryRun:
    """Corroboration Agent (§88): segundo agente busca evidência independente em OUTROS
    sítios, confirmando o escopo. Cada atom buscado recebe um evento EvidenceSearched
    (mesmo NOT_FOUND) para não ser perguntado de novo nesta source/commit."""
    model = model or settings.harness_corroboration_model or settings.harness_model
    effort = effort or settings.harness_effort
    source = db.get(Source, source_id)
    if source is None or not source.repository:
        raise NotFoundError("Source inexistente ou sem repositório")

    try:
        ws = workspace.acquire(source.repository, source.branch, source.commit)
    except RuntimeError as e:
        return _falha_workspace(
            db, source_id=source_id, agent="corroboration", domain=domain,
            capability=capability, model=model, effort=effort, actor=actor, erro=e,
        )
    try:
        if atoms is None:
            atoms = select_evidence_targets(
                db, source=source, domain=domain, capability=capability, commit=ws.commit,
                max_atoms=max_atoms,
            )
        if not atoms:
            raise KernelError("Nenhum candidate elegível para corroboração")

        evid_por_atom = {a.id: _atom_evidence(db, a.id) for a in atoms}
        alvos = []
        for a in atoms:
            evs = evid_por_atom[a.id]
            alvos.append(
                {
                    "atom_id": a.id,
                    "statement": (a.body or {}).get("statement") or a.title,
                    "cited": sorted(
                        {
                            (e.location or {}).get("file")
                            + (f" ({(e.location or {}).get('symbol')})"
                               if (e.location or {}).get("symbol") else "")
                            for e in evs if (e.location or {}).get("file")
                        }
                    ),
                    "anchors": sorted(_atom_anchors(evs)),
                }
            )
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
        por_id = {a.id: a for a in atoms}
        respondidos: dict[str, str] = {}
        for finding in res.structured.get("findings", []):
            atom_id = finding.get("atom_id")
            atom = por_id.get(atom_id)
            if atom is None:
                continue
            verdict = str(finding.get("verdict") or "NOT_FOUND").upper()
            respondidos[atom_id] = verdict
            if verdict == "NOT_FOUND":
                continue
            evidencias = []
            for ev in finding.get("evidence", []):
                construida = _build_evidence(ws, source, ev, agent="code")
                if construida is None:
                    run.evidence_rejected += 1
                    continue
                evidencias.append(construida)
            if not evidencias:
                continue

            # Guarda de escopo: suporte/contradição de trecho sem nenhuma âncora em comum
            # com a evidência original é regra irmã, não a mesma regra.
            originais = _atom_anchors(evid_por_atom[atom_id])
            novas = set()
            for e in evidencias:
                novas |= anchors_of(e.get("excerpt"))
            escopo_diferente = bool(originais) and bool(novas) and not (originais & novas)
            if verdict == "SIMILAR_DIFFERENT_SCOPE" or (
                verdict in ("SUPPORTS", "CONTRADICTS") and escopo_diferente
            ):
                _variant(
                    db, run, source, ws, atom, finding, evidencias, actor=agent_actor,
                    reason="veredito do agente" if verdict == "SIMILAR_DIFFERENT_SCOPE"
                    else f"âncoras sem interseção ({', '.join(sorted(originais))[:120]})",
                )
                continue
            if verdict not in ("SUPPORTS", "CONTRADICTS"):
                continue
            relation = (
                EvidenceRelation.CONTRADICTS if verdict == "CONTRADICTS"
                else EvidenceRelation.SUPPORTS
            )
            adicionou = False
            existentes = evid_por_atom[atom_id]
            for ev in evidencias:
                if relation == EvidenceRelation.SUPPORTS and not _is_new_site(existentes, ev):
                    continue  # mesmo sítio já citado: não soma independência
                if not ev.get("summary"):
                    ev["summary"] = finding.get("note")
                try:
                    e = ksvc.add_evidence(
                        db, atom_id, actor=agent_actor, origin=Origin.AGENT,
                        relation=relation, **ev,
                    )
                except KernelError:
                    run.evidence_rejected += 1
                    continue
                existentes.append(e)
                adicionou = True
                run.reinforcements += 1
            if adicionou:
                _reopen_routing_if_unreviewed(db, atom_id, run_id=str(run.id))
                evaluation.evaluate_atom(db, atom_id, trigger=f"corroboration:{run.id}")

        for a in atoms:
            events.record_event(
                db, events.EVIDENCE_SEARCHED, agent_actor, a.id,
                {
                    "source_id": str(source.id), "commit": ws.commit, "run_id": str(run.id),
                    "stage": "same_source", "verdict": respondidos.get(a.id, "NO_ANSWER"),
                },
            )
        return _finish(db, run, "succeeded")
    finally:
        workspace.destroy(ws)


def run_evidence_search(
    db: Session,
    *,
    source_id: uuid.UUID,
    domain: str,
    capability: str | None,
    actor: str,
    max_batches: int | None = None,
    batch_size: int = 30,
    budget_usd: float | None = 5.0,
    model: str | None = None,
    timeout_min: int = 30,
    executable: str = "claude",
) -> dict:
    """Cascata, estágio 1 (mesma fonte): corrobora em lotes até não restar atom elegível ou
    esgotar `max_batches`. Para cedo por atom: quem chega a CANONICAL sai da seleção."""
    max_batches = max_batches or settings.evidence_search_max_batches
    resumo = {"batches": 0, "atoms": 0, "cost_usd": 0.0, "status": "done", "runs": []}
    source = db.get(Source, source_id)
    if source is None or not source.repository:
        raise NotFoundError("Source inexistente ou sem repositório")
    for _ in range(max_batches):
        try:
            ws = workspace.acquire(source.repository, source.branch, source.commit)
        except RuntimeError as e:
            resumo["status"] = f"workspace: {e}"
            break
        try:
            alvos = select_evidence_targets(
                db, source=source, domain=domain, capability=capability, commit=ws.commit,
                max_atoms=batch_size,
            )
        finally:
            workspace.destroy(ws)
        if not alvos:
            resumo["status"] = "exhausted"
            break
        run = run_corroboration(
            db, source_id=source_id, domain=domain, capability=capability, actor=actor,
            max_atoms=batch_size, budget_usd=budget_usd, model=model, timeout_min=timeout_min,
            executable=executable, atoms=alvos,
        )
        resumo["batches"] += 1
        resumo["atoms"] += len(alvos)
        resumo["cost_usd"] += float(run.cost_usd or 0)
        resumo["runs"].append({"run_id": str(run.id), "status": run.status, "error": run.error})
        if run.status != "succeeded":
            resumo["status"] = run.status
            break
    return resumo
