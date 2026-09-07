"""Policy Engine — resolução com precedência (§32) e roteamento (§86) como testes de tabela."""

from app.kernel.policy import (
    AUTO_APPROVED,
    AWAIT_EVIDENCE,
    NEEDS_HUMAN_REVIEW,
    PROVISIONAL,
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
        "intent_has_external_support",
    }


# ---------- faixa provisória ----------


def _route_sig(score, significance="MEDIUM", floor=0.40, **kw):
    eff = EffectivePolicy(threshold=0.90, provisional_floor=floor)
    base = dict(has_conflict=False, risk="MEDIUM", lint_errors=0)
    base.update(kw)
    return route(score=score, policy=eff, significance=significance, **base)


def test_acima_do_piso_e_abaixo_do_limiar_vira_provisorio():
    d = _route_sig(0.45)
    assert d.outcome == PROVISIONAL
    assert "piso provisório" in d.reason
    assert any(c["check"] == "confidence_above_provisional_floor" for c in d.checks)


def test_abaixo_do_piso_vai_para_humano():
    assert _route_sig(0.30).outcome == NEEDS_HUMAN_REVIEW


def test_bloqueios_duros_nunca_viram_provisorio():
    assert _route_sig(0.60, has_conflict=True).outcome == NEEDS_HUMAN_REVIEW
    assert _route_sig(0.60, risk="CRITICAL").outcome == NEEDS_HUMAN_REVIEW
    assert _route_sig(0.60, lint_errors=1).outcome == NEEDS_HUMAN_REVIEW
    eff = EffectivePolicy(threshold=0.90, provisional_floor=0.40, human_review_required=True)
    d = route(score=0.60, policy=eff, has_conflict=False, risk="MEDIUM", lint_errors=0,
              significance="MEDIUM")
    assert d.outcome == NEEDS_HUMAN_REVIEW


def test_piso_nulo_desliga_a_faixa():
    assert _route_sig(0.60, floor=None).outcome == NEEDS_HUMAN_REVIEW


def test_baixa_relevancia_continua_aguardando_evidencia():
    # LOW nunca ocupa humano nem entra na faixa provisória: aguarda evidência
    d = _route_sig(0.45, significance="LOW", low_significance_threshold=0.60)
    assert d.outcome == AWAIT_EVIDENCE


def test_guarda_de_intencao_so_com_codigo_tem_teto_provisorio():
    # código prova "o sistema faz", não "o negócio quer": INTENDED só com código não canonicaliza
    d = _route_sig(0.95, classification="INTENDED_BEHAVIOR", evidence_types={"SOURCE_CODE", "TEST"})
    assert d.outcome == PROVISIONAL
    assert "teto provisório" in d.reason
    # com banco/documento/humano além do código, passa
    d = _route_sig(0.95, classification="INTENDED_BEHAVIOR",
                   evidence_types={"SOURCE_CODE", "DATABASE"})
    assert d.outcome == AUTO_APPROVED
    # comportamento observado só com código canonicaliza normalmente
    d = _route_sig(0.95, classification="OBSERVED_BEHAVIOR", evidence_types={"SOURCE_CODE"})
    assert d.outcome == AUTO_APPROVED


def test_politica_por_relevancia_e_precedencia():
    policies = [
        _p("m", "significance", "MEDIUM", threshold=0.70, provisional_floor=0.40,
           require_owner_approval=False, min_reviewers=1),
        _p("c", "capability", "ar", threshold=0.85),
    ]
    escopo = AtomScope(domain="finance", capability="ar", kind="rule", risk="MEDIUM",
                       significance="MEDIUM")
    eff = resolve(policies, escopo)
    assert eff.threshold == 0.85  # capability vence significance
    assert eff.provisional_floor == 0.40
    assert eff.owner_required() is False and eff.reviewers_required() == 1
    eff2 = resolve(policies[:1], escopo)
    assert eff2.threshold == 0.70
    # sem significance no escopo, a política de relevância não se aplica
    eff3 = resolve(policies[:1], AtomScope("finance", "ar", "rule", "MEDIUM"))
    assert eff3.threshold == 0.90 and eff3.owner_required() is True
