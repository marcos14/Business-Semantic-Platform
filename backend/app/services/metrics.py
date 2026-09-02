"""Semantic Metrics (PRD §75-§81, §107-§109): consultas sobre o event log e tabelas.

Auditabilidade por construção (D4): nenhuma instrumentação extra — toda métrica
deriva de domain_events + estado atual.
"""

from statistics import median

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.kernel import events
from app.kernel.governance import DecisionAction
from app.kernel.ir.envelope import AtomKind, LifecycleStatus, RelationType
from app.models.auth import Role, RoleBinding
from app.models.knowledge import AtomRelation, DomainEvent, EvidenceLink, KnowledgeAtom
from app.models.review import Vote
from app.services.evaluation import collect_evidence_facts

_CANDIDATE_STATUSES = {
    str(s)
    for s in (
        LifecycleStatus.DISCOVERED,
        LifecycleStatus.CANDIDATE,
        LifecycleStatus.CORROBORATING,
        LifecycleStatus.READY_FOR_EVALUATION,
        LifecycleStatus.NEEDS_HUMAN_REVIEW,
        LifecycleStatus.IN_REVIEW,
        LifecycleStatus.DECISION_PENDING,
        LifecycleStatus.CONFLICTED,
        LifecycleStatus.UNKNOWN,
    )
}

_FINAL_EVENTS = (events.KNOWLEDGE_CANONICALIZED,)


def _atoms(db: Session, domain: str | None, capability: str | None) -> list[KnowledgeAtom]:
    stmt = select(KnowledgeAtom)
    if domain:
        stmt = stmt.where(KnowledgeAtom.domain == domain)
    if capability:
        stmt = stmt.where(KnowledgeAtom.capability == capability)
    return list(db.scalars(stmt))


def _auto_approved_ids(db: Session, ids: set[str]) -> set[str]:
    if not ids:
        return set()
    return set(
        db.scalars(
            select(DomainEvent.atom_id).where(
                DomainEvent.event_type == events.STATUS_CHANGED,
                DomainEvent.payload["to"].astext == str(LifecycleStatus.AUTO_APPROVED),
                DomainEvent.atom_id.in_(ids),
            )
        )
    )


def _has_owner(bindings: list[RoleBinding], domain: str, capability: str | None) -> bool:
    for b in bindings:
        if b.role not in (Role.DECISION_OWNER, Role.ADMINISTRATOR):
            continue
        if b.domain_slug is None or (
            b.domain_slug == domain and (b.capability_slug in (None, capability))
        ):
            return True
    return False


def coverage(db: Session, *, domain: str | None = None, capability: str | None = None) -> dict:
    """Semantic Coverage (§75)."""
    atoms = _atoms(db, domain, capability)
    ids = {a.id for a in atoms}
    rules = [a for a in atoms if a.kind == str(AtomKind.RULE)]
    rule_ids = {r.id for r in rules}

    supported = set(
        db.scalars(
            select(EvidenceLink.atom_id).where(
                EvidenceLink.atom_id.in_(ids), EvidenceLink.relation == "supports"
            )
        )
    )
    voted = set(db.scalars(select(Vote.atom_id).where(Vote.atom_id.in_(ids)))) if ids else set()
    exemplified = set(
        db.scalars(
            select(AtomRelation.from_atom).where(
                AtomRelation.from_atom.in_(rule_ids),
                AtomRelation.type == str(RelationType.EXEMPLIFIED_BY),
            )
        )
    )
    multi_indep = sum(
        1
        for r in rules
        if len({f.lineage for f in collect_evidence_facts(db, r.id) if f.relation == "supports"})
        >= 2
    )
    bindings = list(db.scalars(select(RoleBinding)))
    sem_owner = sum(1 for r in rules if not _has_owner(bindings, r.domain, r.capability))

    return {
        "scope": {"domain": domain, "capability": capability},
        "total_atoms": len(atoms),
        "canonical_atoms": sum(1 for a in atoms if a.status == str(LifecycleStatus.CANONICAL)),
        "candidate_atoms": sum(1 for a in atoms if a.status in _CANDIDATE_STATUSES),
        "auto_approved_atoms": len(_auto_approved_ids(db, ids)),
        "human_reviewed_atoms": len(voted),
        "open_conflicts": sum(
            1
            for a in atoms
            if a.kind == str(AtomKind.CONFLICT) and (a.body or {}).get("state") == "open"
        ),
        "open_questions": sum(
            1
            for a in atoms
            if a.kind == str(AtomKind.QUESTION) and not (a.body or {}).get("answer")
        ),
        "rules_total": len(rules),
        "rules_with_evidence": sum(1 for r in rules if r.id in supported),
        "rules_with_multiple_independent_evidence": multi_indep,
        "rules_without_scenarios": sum(1 for r in rules if r.id not in exemplified),
        "rules_without_owner": sem_owner,
    }


def coverage_by_capability(db: Session, *, domain: str | None = None) -> list[dict]:
    """§107: Coverage by Capability (contagens leves por capability)."""
    linhas: dict[tuple, dict] = {}
    for a in _atoms(db, domain, None):
        r = linhas.setdefault(
            (a.domain, a.capability),
            {"domain": a.domain, "capability": a.capability, "total": 0, "canonical": 0,
             "candidates": 0, "open_conflicts": 0, "open_questions": 0},
        )
        r["total"] += 1
        if a.status == str(LifecycleStatus.CANONICAL):
            r["canonical"] += 1
        if a.status in _CANDIDATE_STATUSES and a.kind not in ("conflict", "question"):
            r["candidates"] += 1
        if a.kind == "conflict" and (a.body or {}).get("state") == "open":
            r["open_conflicts"] += 1
        if a.kind == "question" and not (a.body or {}).get("answer"):
            r["open_questions"] += 1
    return sorted(linhas.values(), key=lambda r: (r["domain"], r["capability"] or ""))


def confidence_distribution(db: Session, *, domain: str | None = None) -> dict:
    """§76: distribuição nos buckets do PRD + % auto vs humano."""
    atoms = [
        a
        for a in _atoms(db, domain, None)
        if a.kind not in ("conflict", "question") and a.confidence is not None
    ]
    buckets = {"0-50": 0, "50-70": 0, "70-90": 0, "90-95": 0, "95-100": 0}
    for a in atoms:
        c = a.confidence * 100
        if c < 50:
            buckets["0-50"] += 1
        elif c < 70:
            buckets["50-70"] += 1
        elif c < 90:
            buckets["70-90"] += 1
        elif c < 95:
            buckets["90-95"] += 1
        else:
            buckets["95-100"] += 1

    rotas = db.execute(
        select(DomainEvent.atom_id, DomainEvent.payload["decision"].astext).where(
            DomainEvent.event_type == events.DECISION_MADE,
            DomainEvent.payload["decision"].astext.in_(
                ["AUTO_APPROVED", "NEEDS_HUMAN_REVIEW"]
            ),
        )
    ).all()
    escopo = {a.id for a in _atoms(db, domain, None)} if domain else None
    decisões: dict[str, str] = {}
    for atom_id, decisao in rotas:
        if escopo is None or atom_id in escopo:
            decisões[atom_id] = decisao  # última decisão de roteamento vence
    total_rotas = len(decisões) or 1
    autos = sum(1 for d in decisões.values() if d == "AUTO_APPROVED")
    return {
        "buckets": buckets,
        "evaluated_atoms": len(decisões),
        "pct_auto_approved": round(autos / total_rotas, 4),
        "pct_needs_human": round((len(decisões) - autos) / total_rotas, 4),
    }


def attention_kpis(db: Session, *, domain: str | None = None) -> dict:
    """§77-§81 + §131: KPIs de atenção humana e automação (latências em wall-clock)."""
    escopo = {a.id for a in _atoms(db, domain, None)}
    evs = list(
        db.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.event_type.in_(
                    [
                        events.HUMAN_REVIEW_REQUESTED,
                        events.DECISION_MADE,
                        events.STATUS_CHANGED,
                        events.ATOM_UPDATED,
                        events.CANONICAL_KNOWLEDGE_CHALLENGED,
                    ]
                )
            )
            .order_by(DomainEvent.id)
        )
    )
    if domain:
        evs = [e for e in evs if e.atom_id in escopo]

    pedido: dict[str, object] = {}
    latencias_min: list[float] = []
    owner_decisions: list[DomainEvent] = []
    editados: set[str] = set()
    for e in evs:
        if e.event_type == events.HUMAN_REVIEW_REQUESTED and e.atom_id not in pedido:
            pedido[e.atom_id] = e.occurred_at
        elif e.event_type == events.ATOM_UPDATED and e.atom_id in pedido:
            editados.add(e.atom_id)
        elif e.event_type == events.DECISION_MADE and "decision_action" in (e.payload or {}):
            owner_decisions.append(e)
            inicio = pedido.pop(e.atom_id, None)
            if inicio is not None:
                latencias_min.append((e.occurred_at - inicio).total_seconds() / 60)

    votos = db.execute(
        select(Vote.reviewer_id, func.count()).group_by(Vote.reviewer_id)
    ).all()

    # §79 automation rate — roteamentos distintos por atom (última decisão)
    rotas = db.execute(
        select(DomainEvent.atom_id, DomainEvent.payload["decision"].astext).where(
            DomainEvent.event_type == events.DECISION_MADE,
            DomainEvent.payload["decision"].astext.in_(["AUTO_APPROVED", "NEEDS_HUMAN_REVIEW"]),
        )
    ).all()
    decisões = {aid: d for aid, d in rotas if (not domain or aid in escopo)}
    autos = {aid for aid, d in decisões.items() if d == "AUTO_APPROVED"}

    # §80 false auto-approval: auto-aprovados depois corrigidos/rejeitados/desafiados
    corrigidos = 0
    if autos:
        challenged = set(
            db.scalars(
                select(DomainEvent.atom_id).where(
                    DomainEvent.event_type == events.CANONICAL_KNOWLEDGE_CHALLENGED,
                    DomainEvent.atom_id.in_(autos),
                )
            )
        )
        alterados = set(
            db.scalars(
                select(KnowledgeAtom.id).where(
                    KnowledgeAtom.id.in_(autos),
                    or_(
                        KnowledgeAtom.status == str(LifecycleStatus.SUPERSEDED),
                        KnowledgeAtom.version > 1,
                    ),
                )
            )
        )
        corrigidos = len(challenged | alterados)

    # §81 override (proxy explicável): decisão do owner contrária ao sinal do sistema
    overrides = 0
    conf = {a.id: a.confidence for a in _atoms(db, domain, None)}
    for e in owner_decisions:
        acao = (e.payload or {}).get("decision_action")
        c = conf.get(e.atom_id)
        if c is None:
            continue
        if (acao == str(DecisionAction.REJECT) and c >= 0.90) or (
            acao == str(DecisionAction.APPROVE) and c < 0.60
        ):
            overrides += 1

    aprovacoes = [
        e for e in owner_decisions
        if (e.payload or {}).get("decision_action") == str(DecisionAction.APPROVE)
    ]
    rejeicoes = [
        e for e in owner_decisions
        if (e.payload or {}).get("decision_action") == str(DecisionAction.REJECT)
    ]
    decididos = len(aprovacoes) + len(rejeicoes) or 1

    return {
        "scope": {"domain": domain},
        "sent_to_human_review": len(
            {e.atom_id for e in evs if e.event_type == events.HUMAN_REVIEW_REQUESTED}
        ),
        "owner_decisions": len(owner_decisions),
        "median_review_latency_min": round(median(latencias_min), 2) if latencias_min else None,
        "avg_review_latency_min": round(sum(latencias_min) / len(latencias_min), 2)
        if latencias_min
        else None,
        "votes_per_reviewer": {str(rid): n for rid, n in votos},
        "pct_approved_unchanged": round(
            sum(1 for e in aprovacoes if e.atom_id not in editados) / decididos, 4
        ),
        "pct_approved_modified": round(
            sum(1 for e in aprovacoes if e.atom_id in editados) / decididos, 4
        ),
        "pct_rejected": round(len(rejeicoes) / decididos, 4),
        "automation_rate": round(len(autos) / len(decisões), 4) if decisões else None,
        "false_auto_approval_rate": round(corrigidos / len(autos), 4) if autos else None,
        "human_override_rate": round(overrides / len(owner_decisions), 4)
        if owner_decisions
        else None,
        "notes": "Latências em wall-clock (não esforço); override é proxy explicável "
        "(REJECT com confidence>=90% ou APPROVE com confidence<60%).",
    }


def audit_dashboard(db: Session, *, domain: str | None = None) -> dict:
    """§109: visão para administradores e owners."""
    escopo = {a.id for a in _atoms(db, domain, None)} if domain else None

    def _distinct(event_type: str, **payload_eq) -> set[str]:
        stmt = select(DomainEvent.atom_id).where(DomainEvent.event_type == event_type)
        for k, v in payload_eq.items():
            stmt = stmt.where(DomainEvent.payload[k].astext == v)
        ids = set(db.scalars(stmt))
        return ids if escopo is None else ids & escopo

    autos = _distinct(events.STATUS_CHANGED, to=str(LifecycleStatus.AUTO_APPROVED))
    aprovados_humanos = _distinct(events.DECISION_MADE, decision_action="APPROVE")
    rejeitados = _distinct(events.DECISION_MADE, decision_action="REJECT")
    reabertos = _distinct(events.CANONICAL_KNOWLEDGE_CHALLENGED)

    # threshold performance: score no momento do roteamento × desfecho
    rotas = db.execute(
        select(
            DomainEvent.atom_id,
            DomainEvent.payload["decision"].astext,
            DomainEvent.payload["confidence"].astext,
        ).where(
            DomainEvent.event_type == events.DECISION_MADE,
            DomainEvent.payload["decision"].astext.in_(["AUTO_APPROVED", "NEEDS_HUMAN_REVIEW"]),
        )
    ).all()
    perf: dict[str, dict[str, int]] = {}
    for atom_id, decisao, conf in rotas:
        if escopo is not None and atom_id not in escopo:
            continue
        try:
            c = float(conf) * 100
        except (TypeError, ValueError):
            continue
        faixa = "0-50" if c < 50 else "50-70" if c < 70 else "70-90" if c < 90 else "90-100"
        perf.setdefault(faixa, {"AUTO_APPROVED": 0, "NEEDS_HUMAN_REVIEW": 0})[decisao] += 1

    return {
        "scope": {"domain": domain},
        "auto_approved": len(autos),
        "human_approved": len(aprovados_humanos),
        "rejected": len(rejeitados),
        "reopened_canonical": len(reabertos),
        "threshold_performance": dict(sorted(perf.items())),
    }
