from app.models.auth import Role

# Hierarquia de papéis (PRD §7): Domain Expert faz tudo de Reviewer; Decision Owner
# também revisa; Administrator passa em qualquer checagem no MVP (revisitar na Fase 3
# se a separação admin ≠ autoridade de decisão precisar ser estrita).
ROLE_IMPLIES: dict[Role, frozenset[Role]] = {
    Role.VIEWER: frozenset({Role.VIEWER}),
    Role.REVIEWER: frozenset({Role.REVIEWER, Role.VIEWER}),
    Role.DOMAIN_EXPERT: frozenset({Role.DOMAIN_EXPERT, Role.REVIEWER, Role.VIEWER}),
    Role.DECISION_OWNER: frozenset({Role.DECISION_OWNER, Role.REVIEWER, Role.VIEWER}),
    Role.ADMINISTRATOR: frozenset(Role),
}


def has_role(user, role: Role, domain: str | None = None, capability: str | None = None) -> bool:
    """Autorização escopada (PRD §103).

    Um binding global (domain_slug=None) vale para qualquer escopo. Um binding
    escopado só vale para o domain (e capability, se restrita) correspondente —
    e nunca satisfaz uma checagem global (domain=None): expertise em Finance
    não implica autoridade em Manufacturing nem autoridade global.
    """
    for b in user.bindings:
        if role not in ROLE_IMPLIES[b.role]:
            continue
        if b.domain_slug is None:
            return True
        if domain is not None and b.domain_slug == domain:
            if b.capability_slug is None or b.capability_slug == capability:
                return True
    return False
