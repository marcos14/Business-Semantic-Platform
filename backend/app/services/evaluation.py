"""Orquestração da avaliação: sinais → score → política → roteamento (§27-§35, §86-§87).

Score é sempre calculado e persistido (append-only). Roteamento só ocorre em
status pré-review (CANDIDATE/CORROBORATING/READY_FOR_EVALUATION) — um atom em
fluxo humano ou canonical nunca é re-roteado automaticamente (§74).
"""

import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.kernel import events
from app.kernel.confidence import EvidenceFact, compute_score
from app.kernel.ir.envelope import EvidenceRelation, LifecycleStatus
from app.kernel.linter import lint_db
from app.kernel.policy import (
    AUTO_APPROVED,
    AtomScope,
    PolicyView,
    resolve,
    route,
)
from app.models.confidence import ConfidenceScore, ConfidenceSignal, Policy
from app.models.knowledge import AtomRelation, Evidence, EvidenceLink
from app.services import knowledge as ksvc
from app.services import notify

SYSTEM_ACTOR = "system:confidence-engine"

ROUTABLE_STATUSES = {
    LifecycleStatus.CANDIDATE,
    LifecycleStatus.CORROBORATING,
    LifecycleStatus.READY_FOR_EVALUATION,
}


def _lineage_key(ev: Evidence) -> str:
    """Heurística de independência (§29): mesmo ARQUIVO = mesma linhagem.

    O arquivo vem antes do source_id: uma Source de repositório inteiro tornaria
    todas as evidências "iguais" (bug corrigido no engine v1.1). Sem arquivo,
    cai para a source; sem ambos, cada evidência é sua própria linhagem.
    """
    loc = ev.location or {}
    if loc.get("file"):
        return f"file:{ev.source_id or loc.get('repository', '')}:{loc['file']}"
    if ev.source_id is not None:
        return f"source:{ev.source_id}"
    return f"evidence:{ev.id}"


def collect_evidence_facts(db: Session, atom_id: str) -> list[EvidenceFact]:
    rows = db.execute(
        select(EvidenceLink, Evidence)
        .join(Evidence, EvidenceLink.evidence_id == Evidence.id)
        .where(EvidenceLink.atom_id == atom_id)
        .order_by(Evidence.created_at)
    ).all()
    return [
        EvidenceFact(
            id=str(ev.id),
            type=ev.type,
            relation=link.relation,
            lineage=_lineage_key(ev),
            created_by=ev.created_by,
            origin=ev.origin,
        )
        for link, ev in rows
    ]


def _has_conflict(db: Session, atom_id: str, facts: list[EvidenceFact]) -> bool:
    if any(f.relation == EvidenceRelation.CONTRADICTS for f in facts):
        return True
    rel = db.scalar(
        select(AtomRelation).where(
            AtomRelation.type == "CONTRADICTS",
            or_(AtomRelation.from_atom == atom_id, AtomRelation.to_atom == atom_id),
        )
    )
    return rel is not None


def load_policies(db: Session) -> list[PolicyView]:
    return [
        PolicyView(
            id=str(p.id),
            name=p.name,
            scope_type=p.scope_type,
            selector=p.selector,
            threshold=p.threshold,
            human_review_required=p.human_review_required,
            min_reviewers=p.min_reviewers,
            require_owner_approval=p.require_owner_approval,
        )
        for p in db.scalars(select(Policy).where(Policy.active.is_(True)))
    ]


def evaluate_atom(
    db: Session, atom_id: str, *, actor: str = SYSTEM_ACTOR, trigger: str = "manual"
) -> dict:
    atom = ksvc.get_atom(db, atom_id)

    # 1. Score (sempre; histórico append-only)
    facts = collect_evidence_facts(db, atom_id)
    result = compute_score(facts, body_size=len(json.dumps(atom.body or {})))
    score_row = ConfidenceScore(
        atom_id=atom.id,
        score=result.score,
        engine_version=result.engine_version,
        trigger=trigger,
        actor=actor,
    )
    db.add(score_row)
    db.flush()
    for s in result.signals:
        db.add(
            ConfidenceSignal(
                score_id=score_row.id,
                name=s.name,
                value=s.value,
                contribution=s.contribution,
                explanation=s.explanation,
            )
        )
    if atom.confidence != result.score:
        events.record_event(
            db,
            events.CONFIDENCE_CHANGED,
            actor,
            atom.id,
            {
                "from": atom.confidence,
                "to": result.score,
                "engine_version": result.engine_version,
            },
        )
        atom.confidence = result.score

    summary: dict = {
        "atom_id": atom.id,
        "score": result.score,
        "engine_version": result.engine_version,
        "explanation": result.explanation_lines(),
        "routed": False,
    }

    # 2. Roteamento (§31/§86) — apenas em status pré-review
    if LifecycleStatus(atom.status) not in ROUTABLE_STATUSES:
        summary["reason_not_routed"] = f"status {atom.status} não é roteável"
        return summary

    eff = resolve(load_policies(db), AtomScope(atom.domain, atom.capability, atom.kind, atom.risk))
    lint_errors = sum(
        1 for f in lint_db(db) if f.atom_id == atom.id and f.severity == "error"
    )
    decision = route(
        score=result.score,
        policy=eff,
        has_conflict=_has_conflict(db, atom.id, facts),
        risk=atom.risk,
        lint_errors=lint_errors,
    )

    # Audit do §87: confidence, threshold, evidence, policy, versões, timestamp
    events.record_event(
        db,
        events.DECISION_MADE,
        actor,
        atom.id,
        {
            "decision": decision.outcome,
            "reason": decision.reason,
            "checks": list(decision.checks),
            "confidence": result.score,
            "engine_version": result.engine_version,
            "policy": eff.as_dict(),
            "evidence": [f.id for f in facts],
            "trigger": trigger,
        },
    )

    if atom.status != LifecycleStatus.READY_FOR_EVALUATION:
        atom = ksvc.change_status(
            db,
            atom.id,
            actor=actor,
            new_status=LifecycleStatus.READY_FOR_EVALUATION,
            reason=f"avaliação ({trigger})",
            expected_lock_version=atom.lock_version,
        )

    if decision.outcome == AUTO_APPROVED:
        atom = ksvc.change_status(
            db,
            atom.id,
            actor=actor,
            new_status=LifecycleStatus.AUTO_APPROVED,
            reason=decision.reason,
            expected_lock_version=atom.lock_version,
            system_action=True,
        )
        # §99: no caminho automático a política É a autoridade — vai a canonical
        atom = ksvc.change_status(
            db,
            atom.id,
            actor=actor,
            new_status=LifecycleStatus.CANONICAL,
            reason="auto-approval por política (§86)",
            expected_lock_version=atom.lock_version,
            authority_granted=True,
        )
    else:
        atom = ksvc.change_status(
            db,
            atom.id,
            actor=actor,
            new_status=LifecycleStatus.NEEDS_HUMAN_REVIEW,
            reason=decision.reason,
            expected_lock_version=atom.lock_version,
        )
        # §73: "Threshold/policy causes review"
        notify.notify_reviewers(
            db,
            atom,
            type="review_needed",
            message=f"Revisão necessária ({decision.reason}): {atom.title}",
        )

    summary.update(
        routed=True,
        decision=decision.outcome,
        reason=decision.reason,
        status=atom.status,
        policy=eff.as_dict(),
    )
    return summary


def latest_confidence(db: Session, atom_id: str) -> dict | None:
    ksvc.get_atom(db, atom_id)
    row = db.scalar(
        select(ConfidenceScore)
        .where(ConfidenceScore.atom_id == atom_id)
        .order_by(ConfidenceScore.computed_at.desc(), ConfidenceScore.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    return {
        "score": row.score,
        "engine_version": row.engine_version,
        "trigger": row.trigger,
        "computed_at": row.computed_at.isoformat(),
        "signals": [
            {
                "name": s.name,
                "value": s.value,
                "contribution": s.contribution,
                "explanation": s.explanation,
            }
            for s in row.signals
        ],
    }
