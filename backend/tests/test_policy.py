"""Policy Engine — resolução com precedência (§32) e roteamento (§86) como testes de tabela."""

from app.kernel.policy import (
    AUTO_APPROVED,
    NEEDS_HUMAN_REVIEW,
    AtomScope,
    EffectivePolicy,
    PolicyView,
    resolve,
    route,
)

SCOPE = AtomScope(domain="finance", capability="ar", kind="rule", risk="MEDIUM")


def _p(id, scope_type, selector=None, **kw):
    return PolicyView(id=id, name=f"pol-{id}", scope_type=scope_type, selector=selector, **kw)


def test_default_90():  # §31
    eff = resolve([], SCOPE)
    assert eff.threshold == 0.90
    assert eff.human_review_required is False


def test_precedencia_risk_sobre_capability_sobre_domain_sobre_global():
    policies = [
        _p("g", "global", threshold=0.90),
        _p("d", "domain", "finance", threshold=0.95),
        _p("c", "capability", "ar", threshold=0.85),
        _p("r", "risk", "MEDIUM", threshold=0.92),
    ]
    assert resolve(policies, SCOPE).threshold == 0.92  # risk vence
    assert resolve(policies[:3], SCOPE).threshold == 0.85  # capability vence domain
    assert resolve(policies[:2], SCOPE).threshold == 0.95  # domain vence global
    assert resolve(policies[:1], SCOPE).threshold == 0.90


def test_politica_de_outro_escopo_nao_se_aplica():
    policies = [_p("d", "domain", "manufacturing", threshold=0.99)]
    assert resolve(policies, SCOPE).threshold == 0.90


def test_proveniencia_registrada():
    eff = resolve([_p("d", "domain", "finance", threshold=0.95)], SCOPE)
    assert "pol-d" in eff.provenance["threshold"]


def test_merge_campo_a_campo():
    policies = [
        _p("g", "global", threshold=0.90),
        _p("k", "atom_kind", "rule", human_review_required=True),  # não define threshold
    ]
    eff = resolve(policies, SCOPE)
    assert eff.threshold == 0.90
    assert eff.human_review_required is True


def _route(score, threshold=0.90, human=False, conflict=False, risk="MEDIUM", lint=0):
    eff = EffectivePolicy(threshold=threshold, human_review_required=human)
    return route(score=score, policy=eff, has_conflict=conflict, risk=risk, lint_errors=lint)


def test_ac_conf_01_auto_approve():
    # confidence 94%, threshold 90%, sem conflito, sem revisão obrigatória
    d = _route(0.94)
    assert d.outcome == AUTO_APPROVED


def test_ac_conf_02_abaixo_do_threshold_vai_para_humano():
    # confidence 89%, threshold 90%
    d = _route(0.89)
    assert d.outcome == NEEDS_HUMAN_REVIEW
    assert "confidence" in d.reason


def test_ac_conf_03_politica_obrigatoria_vence_confidence():
    # confidence 99%, risk critical, human_review_required
    d = _route(0.99, human=True, risk="CRITICAL")
    assert d.outcome == NEEDS_HUMAN_REVIEW


def test_conflito_bloqueia_auto_approval():
    assert _route(0.99, conflict=True).outcome == NEEDS_HUMAN_REVIEW


def test_risk_critical_bloqueia_mesmo_sem_politica():
    assert _route(0.99, risk="CRITICAL").outcome == NEEDS_HUMAN_REVIEW


def test_erro_de_linter_bloqueia():
    assert _route(0.99, lint=1).outcome == NEEDS_HUMAN_REVIEW


def test_checks_completos_para_audit():
    d = _route(0.94)
    assert {c["check"] for c in d.checks} == {
        "no_mandatory_human_policy",
        "no_critical_risk",
        "no_conflict",
        "semantic_validation",
        "confidence_above_threshold",
    }
