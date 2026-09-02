"""State machine do knowledge lifecycle (PRD §26).

Transições inválidas são impossíveis por construção (§123): todo caminho de
mudança de status passa por validate_transition.
"""

from app.kernel.errors import InvalidTransitionError
from app.kernel.ir.envelope import LifecycleStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.DISCOVERED: frozenset({S.CANDIDATE, S.REJECTED}),
    S.CANDIDATE: frozenset(
        {S.CORROBORATING, S.READY_FOR_EVALUATION, S.CONFLICTED, S.UNKNOWN, S.REJECTED}
    ),
    S.CORROBORATING: frozenset({S.READY_FOR_EVALUATION, S.CONFLICTED, S.CANDIDATE}),
    S.READY_FOR_EVALUATION: frozenset(
        {S.AUTO_APPROVED, S.NEEDS_HUMAN_REVIEW, S.CONFLICTED, S.UNKNOWN, S.REJECTED}
    ),
    S.AUTO_APPROVED: frozenset({S.CANONICAL}),
    S.NEEDS_HUMAN_REVIEW: frozenset({S.IN_REVIEW, S.CONFLICTED}),
    S.IN_REVIEW: frozenset(
        {
            S.DECISION_PENDING,
            S.NEEDS_HUMAN_REVIEW,
            S.CONFLICTED,
            S.UNKNOWN,
            S.LEGACY_BUG,
            S.REJECTED,
        }
    ),
    S.DECISION_PENDING: frozenset(
        {S.CANONICAL, S.REJECTED, S.NEEDS_HUMAN_REVIEW, S.LEGACY_BUG, S.UNKNOWN, S.CONFLICTED}
    ),
    S.CONFLICTED: frozenset({S.READY_FOR_EVALUATION, S.IN_REVIEW, S.REJECTED, S.UNKNOWN}),
    S.UNKNOWN: frozenset({S.READY_FOR_EVALUATION, S.CANDIDATE}),
    S.LEGACY_BUG: frozenset({S.CANDIDATE}),
    # §74: evidência contraditória NÃO altera canonical — cria Conflict + Reevaluation.
    S.CANONICAL: frozenset({S.SUPERSEDED}),
    S.REJECTED: frozenset(),
    S.SUPERSEDED: frozenset(),
}

# Estados iniciais válidos na criação (DISCOVERED reservado ao output cru de agentes).
INITIAL_STATUSES = frozenset({S.DISCOVERED, S.CANDIDATE})

# Alvos que exigem autoridade de Decision Owner no escopo do atom (§8, AC-GOV-03).
AUTHORITY_TARGETS = frozenset({S.CANONICAL, S.SUPERSEDED})

# Alvos reservados ao sistema (Confidence/Policy Engine, Fase 2) — nunca via ação humana direta.
SYSTEM_ONLY_TARGETS = frozenset({S.AUTO_APPROVED})


def validate_transition(current: S, new: S) -> None:
    if new not in TRANSITIONS[S(current)]:
        raise InvalidTransitionError(f"Transição inválida: {current} → {new}")


def requires_authority(new: S) -> bool:
    return S(new) in AUTHORITY_TARGETS


def is_system_only(new: S) -> bool:
    return S(new) in SYSTEM_ONLY_TARGETS
