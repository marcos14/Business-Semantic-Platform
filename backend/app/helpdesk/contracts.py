import enum


class ConsumerProfile(enum.StrEnum):
    DIRECT = "helpdesk_direct"
    COPILOT_N1 = "helpdesk_copilot_n1"
    COPILOT_N2 = "helpdesk_copilot_n2"
    COPILOT_N3 = "helpdesk_copilot_n3"


class Answerability(enum.StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    CONFLICTED = "CONFLICTED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class RecommendedAction(enum.StrEnum):
    ANSWER = "ANSWER"
    ANSWER_WITH_CAUTION = "ANSWER_WITH_CAUTION"
    ASK_CLARIFYING = "ASK_CLARIFYING"
    ESCALATE = "ESCALATE"


class FreshnessStatus(enum.StrEnum):
    FRESH = "FRESH"
    POTENTIALLY_STALE = "POTENTIALLY_STALE"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ScopeMatch(enum.StrEnum):
    EXACT = "EXACT"
    COMPATIBLE = "COMPATIBLE"
    UNKNOWN = "UNKNOWN"
    MISMATCH = "MISMATCH"


class FeedbackOutcome(enum.StrEnum):
    RESOLVED = "RESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    ESCALATED = "ESCALATED"
    REOPENED = "REOPENED"
    INCORRECT = "INCORRECT"
    ABANDONED = "ABANDONED"
    UNKNOWN = "UNKNOWN"


RETRIEVAL_VERSION = "helpdesk-v1"
