from types import SimpleNamespace

from app.models.auth import Role
from app.rbac.roles import has_role


def _user(*bindings: tuple[Role, str | None, str | None]):
    return SimpleNamespace(
        bindings=[
            SimpleNamespace(role=r, domain_slug=d, capability_slug=c) for r, d, c in bindings
        ]
    )


def test_binding_global_vale_para_qualquer_escopo():
    u = _user((Role.REVIEWER, None, None))
    assert has_role(u, Role.REVIEWER)
    assert has_role(u, Role.REVIEWER, domain="finance")
    assert has_role(u, Role.VIEWER, domain="manufacturing")


def test_binding_escopado_nao_vaza_para_outro_domain():
    # PRD §103: Domain Expert em Finance não implica authority em Manufacturing.
    u = _user((Role.DOMAIN_EXPERT, "finance", None))
    assert has_role(u, Role.DOMAIN_EXPERT, domain="finance")
    assert not has_role(u, Role.DOMAIN_EXPERT, domain="manufacturing")
    assert not has_role(u, Role.DOMAIN_EXPERT)  # checagem global exige binding global


def test_hierarquia_de_papeis():
    u = _user((Role.DOMAIN_EXPERT, "finance", None))
    assert has_role(u, Role.REVIEWER, domain="finance")
    assert has_role(u, Role.VIEWER, domain="finance")
    assert not has_role(u, Role.DECISION_OWNER, domain="finance")


def test_escopo_por_capability():
    u = _user((Role.DECISION_OWNER, "finance", "accounts-receivable"))
    assert has_role(u, Role.DECISION_OWNER, domain="finance", capability="accounts-receivable")
    assert not has_role(u, Role.DECISION_OWNER, domain="finance", capability="billing")
    assert not has_role(u, Role.DECISION_OWNER, domain="finance")


def test_administrator_implica_tudo():
    u = _user((Role.ADMINISTRATOR, None, None))
    assert has_role(u, Role.DECISION_OWNER, domain="finance")
    assert has_role(u, Role.ADMINISTRATOR)


def test_reviewer_nao_e_domain_expert():
    u = _user((Role.REVIEWER, None, None))
    assert not has_role(u, Role.DOMAIN_EXPERT, domain="finance")
