"""Enums e regras do envelope comum dos Knowledge Atoms (PRD §13-§14, §25-§26, §34)."""

import enum
import re


class AtomKind(enum.StrEnum):
    """Tipos do Business Semantic IR (PRD §13). Evidence é entidade própria, não kind."""

    CONCEPT = "concept"
    RULE = "rule"
    DECISION = "decision"
    INVARIANT = "invariant"
    STATE = "state"
    TRANSITION = "transition"
    EVENT = "event"
    PROCESS = "process"
    SCENARIO = "scenario"
    EXCEPTION = "exception"
    CONFLICT = "conflict"
    QUESTION = "question"
    CAPABILITY = "capability"


class LifecycleStatus(enum.StrEnum):
    """Estados do knowledge lifecycle (PRD §26)."""

    DISCOVERED = "DISCOVERED"
    CANDIDATE = "CANDIDATE"
    CORROBORATING = "CORROBORATING"
    READY_FOR_EVALUATION = "READY_FOR_EVALUATION"
    AUTO_APPROVED = "AUTO_APPROVED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    DECISION_PENDING = "DECISION_PENDING"
    CANONICAL = "CANONICAL"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    # Estados especiais
    CONFLICTED = "CONFLICTED"
    UNKNOWN = "UNKNOWN"
    LEGACY_BUG = "LEGACY_BUG"


class Classification(enum.StrEnum):
    """PRD §25."""

    OBSERVED_BEHAVIOR = "OBSERVED_BEHAVIOR"
    INTENDED_BEHAVIOR = "INTENDED_BEHAVIOR"
    MANDATED_BEHAVIOR = "MANDATED_BEHAVIOR"
    LEGACY_QUIRK = "LEGACY_QUIRK"
    KNOWN_BUG = "KNOWN_BUG"
    DEPRECATED_BEHAVIOR = "DEPRECATED_BEHAVIOR"
    UNKNOWN = "UNKNOWN"


class RiskLevel(enum.StrEnum):
    """PRD §34."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Significance(enum.StrEnum):
    """Relevância de negócio do conhecimento — a régua do que merece atenção humana.

    TRIVIAL: validação genérica/técnica (campo obrigatório, data inicial > final, máscara,
             log, UI). Não é conhecimento de negócio: descartado na ingestão.
    LOW:     detalhe operacional com algum significado de negócio. Nunca vai a humano:
             auto-aprova com régua reduzida ou aguarda evidência.
    MEDIUM:  regra operacional, cálculo auxiliar, condição de processo. Fluxo normal.
    HIGH:    muda dinheiro, imposto, estoque, status ou decisão; políticas e exceções.
    """

    TRIVIAL = "TRIVIAL"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Origin(enum.StrEnum):
    AGENT = "agent"
    HUMAN = "human"


class EvidenceType(enum.StrEnum):
    """PRD §23."""

    SOURCE_CODE = "SOURCE_CODE"
    TEST = "TEST"
    DOCUMENT = "DOCUMENT"
    DATABASE = "DATABASE"
    RUNTIME = "RUNTIME"
    API = "API"
    UI = "UI"
    CONFIGURATION = "CONFIGURATION"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    DOMAIN_EXPERT = "DOMAIN_EXPERT"
    EXTERNAL_RULE = "EXTERNAL_RULE"


class EvidenceRelation(enum.StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


class RelationType(enum.StrEnum):
    """Edges do graph semântico (PRD §54). EVIDENCED_BY é derivado dos evidence_links."""

    DEPENDS_ON = "DEPENDS_ON"
    AFFECTS = "AFFECTS"
    USED_BY = "USED_BY"
    GOVERNS = "GOVERNS"
    TRIGGERS = "TRIGGERS"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"
    EXEMPLIFIED_BY = "EXEMPLIFIED_BY"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"


class SourceType(enum.StrEnum):
    """PRD §10."""

    SOURCE_CODE = "source_code"
    AUTOMATED_TEST = "automated_test"
    DOCUMENTATION = "documentation"
    DATABASE_SCHEMA = "database_schema"
    API = "api"
    CONFIGURATION = "configuration"
    RUNTIME_TRACE = "runtime_trace"
    MANUAL = "manual"
    TICKET = "ticket"
    HUMAN_INPUT = "human_input"


# IDs no estilo do PRD (§15-§22): segmentos maiúsculos separados por ponto,
# ex.: FINANCE.ACCOUNTS-RECEIVABLE.RULE.0012
ATOM_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]*(\.[A-Z0-9][A-Z0-9-]*)+$")


def validate_atom_id(atom_id: str) -> str:
    if not ATOM_ID_PATTERN.match(atom_id) or len(atom_id) > 300:
        raise ValueError(
            f"ID de atom inválido: {atom_id!r} (esperado segmentos MAIÚSCULOS separados por ponto)"
        )
    return atom_id


def id_prefix(domain: str, capability: str | None, kind: AtomKind) -> str:
    cap = (capability or "GLOBAL").upper()
    return f"{domain.upper()}.{cap}.{kind.value.upper()}"
