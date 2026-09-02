"""Policy Engine (PRD §31-§35, §86) — resolução de políticas e roteamento puros.

Políticas são DADOS (tabela `policies`); aqui vive apenas a lógica: resolução
com precedência (§32) e a decisão de roteamento (§86), ambas explicáveis —
cada campo efetivo carrega a proveniência de qual política o definiu.
"""

from dataclasses import dataclass, field

from app.kernel.ir.envelope import RiskLevel

DEFAULT_THRESHOLD = 0.90  # §31

# Precedência (§32): Risk > Capability > Atom kind > Domain > Global.
# (Atom kind não aparece na lista do §32; fica entre domain e capability por
# ser mais específico que domain e menos que uma capability concreta.)
PRECEDENCE: dict[str, int] = {
    "global": 100,
    "domain": 200,
    "atom_kind": 300,
    "capability": 400,
    "risk": 500,
}

SCOPE_TYPES = frozenset(PRECEDENCE)


@dataclass(frozen=True)
class PolicyView:
    id: str
    name: str
    scope_type: str  # global | domain | atom_kind | capability | risk
    selector: str | None  # None para global
    threshold: float | None = None
    human_review_required: bool | None = None
    min_reviewers: int | None = None
    require_owner_approval: bool | None = None


@dataclass(frozen=True)
class AtomScope:
    domain: str
    capability: str | None
    kind: str
    risk: str | None


@dataclass
class EffectivePolicy:
    threshold: float = DEFAULT_THRESHOLD
    human_review_required: bool = False
    min_reviewers: int | None = None
    require_owner_approval: bool | None = None
    provenance: dict[str, str] = field(default_factory=dict)  # campo -> política que o definiu

    def as_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "human_review_required": self.human_review_required,
            "min_reviewers": self.min_reviewers,
            "require_owner_approval": self.require_owner_approval,
            "provenance": self.provenance,
        }


def _matches(p: PolicyView, scope: AtomScope) -> bool:
    match p.scope_type:
        case "global":
            return True
        case "domain":
            return p.selector == scope.domain
        case "capability":
            return scope.capability is not None and p.selector == scope.capability
        case "atom_kind":
            return p.selector == scope.kind
        case "risk":
            return scope.risk is not None and p.selector == scope.risk
    return False


def resolve(policies: list[PolicyView], scope: AtomScope) -> EffectivePolicy:
    """Merge campo a campo em ordem crescente de precedência (§32)."""
    eff = EffectivePolicy()
    eff.provenance["threshold"] = f"default ({DEFAULT_THRESHOLD:.0%}, §31)"
    aplicaveis = sorted(
        (p for p in policies if _matches(p, scope)), key=lambda p: PRECEDENCE[p.scope_type]
    )
    for p in aplicaveis:
        rotulo = f"{p.name} [{p.scope_type}:{p.selector or '*'}]"
        if p.threshold is not None:
            eff.threshold = p.threshold
            eff.provenance["threshold"] = rotulo
        if p.human_review_required is not None:
            eff.human_review_required = p.human_review_required
            eff.provenance["human_review_required"] = rotulo
        if p.min_reviewers is not None:
            eff.min_reviewers = p.min_reviewers
            eff.provenance["min_reviewers"] = rotulo
        if p.require_owner_approval is not None:
            eff.require_owner_approval = p.require_owner_approval
            eff.provenance["require_owner_approval"] = rotulo
    return eff


AUTO_APPROVED = "AUTO_APPROVED"
NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


@dataclass(frozen=True)
class RouteDecision:
    outcome: str
    checks: tuple[dict, ...]  # cada condição do §86 avaliada, para o audit §87
    reason: str

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "reason": self.reason, "checks": list(self.checks)}


def route(
    *,
    score: float,
    policy: EffectivePolicy,
    has_conflict: bool,
    risk: str | None,
    lint_errors: int,
) -> RouteDecision:
    """Decisão do §86: todas as condições precisam passar para auto-approval."""
    checks = (
        {
            "check": "no_mandatory_human_policy",
            "passed": not policy.human_review_required,
            "detail": policy.provenance.get("human_review_required", "sem política obrigatória"),
        },
        {
            "check": "no_critical_risk",
            "passed": risk != RiskLevel.CRITICAL,
            "detail": f"risk={risk or 'não classificado'}",
        },
        {"check": "no_conflict", "passed": not has_conflict, "detail": f"conflito={has_conflict}"},
        {
            "check": "semantic_validation",
            "passed": lint_errors == 0,
            "detail": f"{lint_errors} erro(s) de linter",
        },
        {
            "check": "confidence_above_threshold",
            "passed": score >= policy.threshold,
            "detail": f"confidence {score:.2%} vs threshold {policy.threshold:.2%} "
            f"({policy.provenance.get('threshold', '')})",
        },
    )
    falha = next((c for c in checks if not c["passed"]), None)
    if falha is None:
        return RouteDecision(AUTO_APPROVED, checks, "todas as condições do §86 satisfeitas")
    return RouteDecision(
        NEEDS_HUMAN_REVIEW, checks, f"reprovado em {falha['check']}: {falha['detail']}"
    )
