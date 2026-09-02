"""AtomTypeRegistry: mapeia kind -> schema do body.

Extensibilidade (NFR §121): um kind novo entra por `register()` — sem migração
de banco, pois o body é JSONB validado na escrita.
"""

from pydantic import BaseModel, ValidationError

from app.kernel.errors import BodyValidationError
from app.kernel.ir import kinds
from app.kernel.ir.envelope import AtomKind

_REGISTRY: dict[str, type[BaseModel]] = {
    AtomKind.CONCEPT: kinds.ConceptBody,
    AtomKind.RULE: kinds.RuleBody,
    AtomKind.DECISION: kinds.DecisionBody,
    AtomKind.INVARIANT: kinds.InvariantBody,
    AtomKind.STATE: kinds.StateBody,
    AtomKind.TRANSITION: kinds.TransitionBody,
    AtomKind.EVENT: kinds.EventBody,
    AtomKind.PROCESS: kinds.ProcessBody,
    AtomKind.SCENARIO: kinds.ScenarioBody,
    AtomKind.EXCEPTION: kinds.ExceptionBody,
    AtomKind.CONFLICT: kinds.ConflictBody,
    AtomKind.QUESTION: kinds.QuestionBody,
    AtomKind.CAPABILITY: kinds.CapabilityBody,
}


def register(kind: str, schema: type[BaseModel]) -> None:
    _REGISTRY[str(kind)] = schema


def known_kinds() -> list[str]:
    return sorted(_REGISTRY)


def body_schema(kind: str) -> type[BaseModel]:
    try:
        return _REGISTRY[str(kind)]
    except KeyError:
        raise BodyValidationError(f"Kind desconhecido: {kind!r}") from None


def validate_body(kind: str, body: dict | None) -> dict:
    """Valida e normaliza o body de um atom. Levanta BodyValidationError."""
    schema = body_schema(kind)
    try:
        return schema.model_validate(body or {}).model_dump()
    except ValidationError as e:
        erros = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise BodyValidationError(f"Body inválido para kind {kind!r}: {erros}") from None
