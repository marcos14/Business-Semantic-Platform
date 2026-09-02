"""Schemas do body específico de cada kind (PRD §15-§22).

Campos comuns (title, description, domain, capability, classification, risk,
scope, effective, confidence) vivem no envelope — aqui fica só o que é
particular do kind. `extra="forbid"` garante que campo desconhecido é erro.
"""

from pydantic import BaseModel, ConfigDict, Field


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConceptBody(_Body):
    """§15 — conceito de negócio."""

    synonyms: list[str] = Field(default_factory=list)


class RuleBody(_Body):
    """§16 — afirmação normativa."""

    statement: str = Field(min_length=1)


class DecisionBody(_Body):
    """§17 — decisão baseada em inputs."""

    inputs: list[str] = Field(min_length=1)
    output: str = Field(min_length=1)
    logic: dict | None = None  # ex.: {"type": "decision_table", "rows": [...]}


class InvariantBody(_Body):
    """§18 — propriedade que deve permanecer verdadeira."""

    statement: str = Field(min_length=1)


class StateBody(_Body):
    """§19 — estado relevante (o nome do estado é o title do envelope)."""

    order: int | None = None


class TransitionBody(_Body):
    """§20 — mudança válida de estado. from/to/conditions referenciam atom IDs."""

    from_state: str = Field(min_length=1)
    to_state: str = Field(min_length=1)
    trigger: str | None = None
    conditions: list[str] = Field(default_factory=list)


class EventBody(_Body):
    """Evento de negócio (nome no title do envelope)."""

    payload_fields: list[str] = Field(default_factory=list)


class ProcessBody(_Body):
    """§68 — fluxo simples; steps: {id, type: step|decision|transition|event|condition, ...}."""

    steps: list[dict] = Field(default_factory=list)


class ScenarioBody(_Body):
    """§21 — exemplo concreto (given/when/then)."""

    given: dict = Field(default_factory=dict)
    when: dict = Field(default_factory=dict)
    then: dict = Field(default_factory=dict)


class ExceptionBody(_Body):
    """§22 — exceção a uma regra. applies_to referencia um atom ID."""

    applies_to: str = Field(min_length=1)
    condition: str = Field(min_length=1)


class ConflictBody(_Body):
    """§48-§50 — assertions incompatíveis; nunca auto-merged (P7, AC-CON-01).

    `about`: conflito de evidência sobre UM atom (inclui §74, com reevaluation=True).
    `assertions`: conflito entre DOIS OU MAIS atoms ([{atom_id, statement}]).
    O estado do conflito é do próprio conflito (o status do atom fica CONFLICTED).
    """

    topic: str = Field(min_length=1)
    about: str | None = None
    assertions: list[dict] = Field(default_factory=list)
    reevaluation: bool = False  # §74: Reevaluation Request sobre canonical
    state: str = "open"  # open | resolved | unresolved
    resolution: dict | None = None


class QuestionBody(_Body):
    """§51 — pergunta aberta."""

    question: str = Field(min_length=1)
    answer: str | None = None
    assigned_to: str | None = None
    converted_to: str | None = None  # id da rule criada a partir da resposta


class CapabilityBody(_Body):
    """Capability como atom navegável (§52); metadados livres."""

    tags: list[str] = Field(default_factory=list)
