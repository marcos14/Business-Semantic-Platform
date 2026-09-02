"""Domain events (PRD §98) — gravados na MESMA transação da mutação (outbox).

O audit trail (§69-§70) É este log: não existe caminho de escrita que não
passe pelos serviços que emitem eventos.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.knowledge import DomainEvent

# Nomes dos eventos (§98 + operacionais do kernel)
CANDIDATE_DISCOVERED = "CandidateDiscovered"
EVIDENCE_ADDED = "EvidenceAdded"
STATUS_CHANGED = "StatusChanged"
ATOM_UPDATED = "AtomUpdated"
RELATION_ADDED = "RelationAdded"
HUMAN_REVIEW_REQUESTED = "HumanReviewRequested"
KNOWLEDGE_CANONICALIZED = "KnowledgeCanonicalized"
DECISION_MADE = "DecisionMade"
VOTE_SUBMITTED = "VoteSubmitted"
CONFIDENCE_CHANGED = "ConfidenceChanged"
CONFLICT_DETECTED = "ConflictDetected"
CANONICAL_KNOWLEDGE_CHALLENGED = "CanonicalKnowledgeChallenged"


def record_event(
    db: Session,
    event_type: str,
    actor: str,
    atom_id: str | None = None,
    payload: dict | None = None,
) -> DomainEvent:
    ev = DomainEvent(
        event_type=event_type,
        actor=actor,
        atom_id=atom_id,
        payload=payload or {},
        occurred_at=datetime.now(UTC),
    )
    db.add(ev)
    return ev
