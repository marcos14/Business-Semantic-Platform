"""Policy Engine (PRD §31-§35, §86) — resolução de políticas e roteamento puros.

Políticas são DADOS (tabela `policies`); aqui vive apenas a lógica: resolução
com precedência (§32) e a decisão de roteamento (§86), ambas explicáveis —
cada campo efetivo carrega a proveniência de qual política o definiu.

Três faixas de saída do roteamento:
- AUTO_APPROVED  → CANONICAL: confiança >= limiar e todas as condições do §86.
- PROVISIONAL    → publicado com rótulo: confiança >= piso provisório, sem conflito, sem
                   risco crítico, sem política de revisão obrigatória, linter limpo.
- NEEDS_HUMAN_REVIEW: o resto (conflito, crítico, política obrigatória, abaixo do piso).
"""

from dataclasses import dataclass, field

from app.kernel.ir.envelope import (
    CODE_EVIDENCE_TYPES,
    INTENT_CLASSIFICATIONS,
    RiskLevel,
)

DEFAULT_THRESHOLD = 0.90  # §31
# Piso da faixa provisória quando nenhuma política define outro. Na engine padrão equivale a
# "dois arquivos de código independentes concordam".
DEFAULT_PROVISIONAL_FLOOR = 0.40

# Precedência (§32): Risk > Capability > Significance > Atom kind > Domain > Global.
# (Atom kind e significance não aparecem na lista do §32; ficam entre domain e capability
# por serem mais específicos que domain e menos que uma capability concreta.)
PRECEDENCE: dict[str, int] = {
    "global": 100,
    "domain": 200,
    "atom_kind": 300,
    "significance": 350,
    "capability": 400,
    "risk": 500,
}

SCOPE_TYPES = frozenset(PRECEDENCE)


@dataclass(frozen=True)
class PolicyView:
    id: str
    name: str
    scope_type: str  # global | domain | atom_kind | significance | capability | risk
    selector: str | None  # None para global
    threshold: float | None = None
    human_review_required: bool | None = None
    min_reviewers: int | None = None
    require_owner_approval: bool | None = None
    provisional_floor: float | None = None


@dataclass(frozen=True)
class AtomScope:
    domain: str
    capability: str | None
    kind: str
    risk: str | None
    significance: str | None = None


@dataclass
class EffectivePolicy:
    threshold: float = DEFAULT_THRESHOLD
    human_review_required: bool = False
    min_reviewers: int | None = None
    require_owner_approval: bool | None = None
    provisional_floor: float | None = DEFAULT_PROVISIONAL_FLOOR
    provenance: dict[str, str] = field(default_factory=dict)  # campo -> política que o definiu

    def as_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "human_review_required": self.human_review_required,
            "min_reviewers": self.min_reviewers,
            "require_owner_approval": self.require_owner_approval,
            "provisional_floor": self.provisional_floor,
            "provenance": self.provenance,
        }

    def owner_required(self) -> bool:
        """Sem política dizendo o contrário, o caminho humano continua exigindo o owner."""
        return self.require_owner_approval is not False

    def reviewers_required(self) -> int:
        return max(1, self.min_reviewers or 1)


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
        case "significance":
            return scope.significance is not None and p.selector == scope.significance
        case "risk":
            return scope.risk is not None and p.selector == scope.risk
    return False


def resolve(policies: list[PolicyView], scope: AtomScope) -> EffectivePolicy:
    """Merge campo a campo em ordem crescente de precedência (§32)."""
    eff = EffectivePolicy()
    eff.provenance["threshold"] = f"default ({DEFAULT_THRESHOLD:.0%}, §31)"
    eff.provenance["provisional_floor"] = f"default ({DEFAULT_PROVISIONAL_FLOOR:.0%})"
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
        if p.provisional_floor is not None:
            eff.provisional_floor = p.provisional_floor
            eff.provenance["provisional_floor"] = rotulo
    return eff


AUTO_APPROVED = "AUTO_APPROVED"
PROVISIONAL = "PROVISIONAL"
NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
# Baixa relevância sem confiança suficiente: não vale o tempo de um revisor. Fica
# aguardando evidência (corroboração/reforço reavaliam automaticamente).
AWAIT_EVIDENCE = "AWAIT_EVIDENCE"

_HARD_BLOCKS = (
    "no_mandatory_human_policy",
    "no_critical_risk",
    "no_conflict",
    "semantic_validation",
)
# Só conhecimento com relevância classificada entra na faixa provisória.
PROVISIONAL_SIGNIFICANCES = frozenset({"MEDIUM", "HIGH"})


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
    significance: str | None = None,
    low_significance_threshold: float | None = None,
    classification: str | None = None,
    evidence_types: frozenset[str] | set[str] | None = None,
) -> RouteDecision:
    """Decisão do §86: todas as condições precisam passar para auto-approval.

    Régua de relevância:
    - SYSTEMIC (comportamento objetivo, verificável no código): a evidência verificada basta.
      Aprova sem olhar confiança nem política de revisão obrigatória — salvo conflito, erro
      de linter ou risco crítico, que ainda exigem gente.
    - LOW usa o menor entre o threshold da política e `low_significance_threshold`; se ainda
      assim não passar, vai para AWAIT_EVIDENCE em vez de ocupar um revisor humano.

    Faixa provisória: quem não chega ao limiar mas passa do piso, sem nenhum bloqueio
    (conflito, crítico, política obrigatória, linter), é publicado como PROVISIONAL.

    Guarda de intenção: INTENDED/MANDATED sustentado só por código/teste não canonicaliza
    sozinho — código prova o que o sistema faz, não o que o negócio quer. Teto PROVISIONAL.
    """
    sistemico = significance == "SYSTEMIC"
    baixa = significance == "LOW"
    limiar = policy.threshold
    origem_limiar = policy.provenance.get("threshold", "")
    if baixa and low_significance_threshold is not None and low_significance_threshold < limiar:
        limiar = low_significance_threshold
        origem_limiar = f"régua reduzida para baixa relevância ({limiar:.0%})"
    tipos = {str(t) for t in (evidence_types or ())}
    so_codigo = bool(tipos) and tipos <= {str(t) for t in CODE_EVIDENCE_TYPES}
    intencao = classification in {str(c) for c in INTENT_CLASSIFICATIONS}
    intencao_sem_apoio = intencao and so_codigo
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
            "passed": score >= limiar,
            "detail": f"confidence {score:.2%} vs threshold {limiar:.2%} ({origem_limiar})",
        },
        {
            "check": "intent_has_external_support",
            "passed": not intencao_sem_apoio,
            "detail": (
                f"{classification} sustentado só por código/teste: prova comportamento, "
                "não intenção (teto provisório)"
                if intencao_sem_apoio
                else "classificação não afirma intenção, ou há evidência além do código"
            ),
        },
    )
    if sistemico:
        bloqueio = next(
            (c for c in checks if not c["passed"]
             and c["check"] in ("no_conflict", "semantic_validation", "no_critical_risk")),
            None,
        )
        checks = checks + (
            {
                "check": "systemic_objective",
                "passed": bloqueio is None,
                "detail": "critério sistêmico: comportamento objetivo verificado no código; "
                "confiança e política de revisão não se aplicam",
            },
        )
        if bloqueio is None:
            return RouteDecision(
                AUTO_APPROVED, checks,
                "critério sistêmico: evidência verificada basta, sem revisão humana",
            )
        return RouteDecision(
            NEEDS_HUMAN_REVIEW, checks,
            f"sistêmico, mas reprovado em {bloqueio['check']}: {bloqueio['detail']}",
        )
    falha = next((c for c in checks if not c["passed"]), None)
    if falha is None:
        return RouteDecision(AUTO_APPROVED, checks, "todas as condições do §86 satisfeitas")
    if baixa and not has_conflict and risk != RiskLevel.CRITICAL:
        return RouteDecision(
            AWAIT_EVIDENCE, checks,
            f"baixa relevância sem confiança suficiente ({falha['check']}: {falha['detail']}) "
            "— aguarda evidência em vez de revisão humana",
        )
    # Faixa provisória: relevância classificada (MEDIUM/HIGH), nenhum bloqueio duro e
    # confiança acima do piso. Sem relevância (não triado, criado por humano) o AC-CONF-02
    # continua valendo: abaixo do limiar vai a humano.
    bloqueios = [c for c in checks if not c["passed"] and c["check"] in _HARD_BLOCKS]
    piso = policy.provisional_floor
    elegivel = significance in PROVISIONAL_SIGNIFICANCES
    if elegivel and not bloqueios and piso is not None and score >= piso:
        motivo = (
            f"confiança {score:.2%} acima do piso provisório {piso:.2%} "
            f"({policy.provenance.get('provisional_floor', '')})"
        )
        if intencao_sem_apoio and score >= limiar:
            motivo = f"teto provisório: {falha['detail']}"
        checks = checks + (
            {
                "check": "confidence_above_provisional_floor",
                "passed": True,
                "detail": f"confidence {score:.2%} vs piso {piso:.2%}",
            },
        )
        return RouteDecision(PROVISIONAL, checks, motivo)
    return RouteDecision(
        NEEDS_HUMAN_REVIEW, checks, f"reprovado em {falha['check']}: {falha['detail']}"
    )
