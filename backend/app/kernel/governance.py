"""Conceitos puros de governança: ações (§41/§43), Kanban (§38) e priorização (§84)."""

import enum
from dataclasses import dataclass

from app.kernel.ir.envelope import LifecycleStatus as S


class ReviewAction(enum.StrEnum):
    """Ações de voto do reviewer (PRD §41)."""

    CONFIRM = "CONFIRM"
    REJECT = "REJECT"
    CONFIRM_WITH_EXCEPTION = "CONFIRM_WITH_EXCEPTION"
    OBSERVED_ONLY = "OBSERVED_ONLY"
    LEGACY_BUG = "LEGACY_BUG"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    NEEDS_SPECIALIST = "NEEDS_SPECIALIST"
    NOT_MY_DOMAIN = "NOT_MY_DOMAIN"


class DecisionAction(enum.StrEnum):
    """Ações do Decision Owner (PRD §43; split/merge chegam na Fase 5)."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RECLASSIFY = "RECLASSIFY"
    MARK_KNOWN_BUG = "MARK_KNOWN_BUG"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    ADD_EXCEPTION = "ADD_EXCEPTION"


# Votos assertivos viram evidence humana (§24)
ASSERTIVE_ACTIONS = frozenset(
    {ReviewAction.CONFIRM, ReviewAction.CONFIRM_WITH_EXCEPTION, ReviewAction.REJECT}
)

# Status em que votar/comentar faz sentido
REVIEWABLE_STATUSES = frozenset(
    {S.NEEDS_HUMAN_REVIEW, S.IN_REVIEW, S.CORROBORATING, S.DECISION_PENDING, S.CONFLICTED}
)

# Kanban (§38): coluna -> statuses do lifecycle
KANBAN_COLUMNS: dict[str, tuple[S, ...]] = {
    "needs_review": (S.NEEDS_HUMAN_REVIEW,),
    "in_discussion": (S.IN_REVIEW,),
    "needs_evidence": (S.CORROBORATING,),
    "needs_decision": (S.DECISION_PENDING,),
    "approved": (S.AUTO_APPROVED, S.CANONICAL),
    "rejected": (S.REJECTED, S.LEGACY_BUG),
}

_RISK_WEIGHT = {"CRITICAL": 4.0, "HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0, None: 1.5}


@dataclass(frozen=True)
class Priority:
    score: float
    breakdown: dict[str, float]

    def as_dict(self) -> dict:
        return {"score": round(self.score, 2), "breakdown": self.breakdown}


def review_priority(
    *,
    risk: str | None,
    confidence: float | None,
    threshold: float = 0.90,
    conflict_count: int = 0,
    age_days: float = 0.0,
    centrality: int = 0,
) -> Priority:
    """Score composto do §84 — cada termo visível no breakdown (explicável)."""
    termos = {
        "risk": _RISK_WEIGHT.get(risk, 1.5),
        "conflict_severity": min(conflict_count * 1.5, 4.5),
        "confidence_gap": round(max(threshold - (confidence or 0.0), 0.0) * 3, 2),
        "age": round(min(age_days / 30.0, 1.0), 2),
        "graph_centrality": round(min(centrality / 10.0, 1.0), 2),
    }
    return Priority(score=sum(termos.values()), breakdown=termos)


def recommend(
    *, confidence: float | None, threshold: float = 0.90, has_conflict: bool = False
) -> str:
    """Recomendação heurística exibida no resumo do owner (§44). Nunca decide (P8)."""
    c = confidence or 0.0
    if has_conflict:
        return ReviewAction.NEEDS_MORE_EVIDENCE
    if c >= threshold:
        return ReviewAction.CONFIRM
    if c < 0.60:
        return ReviewAction.NEEDS_MORE_EVIDENCE
    return ReviewAction.CONFIRM_WITH_EXCEPTION
