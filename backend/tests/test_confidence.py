"""Confidence Engine v1 — puro, determinístico, explicável (§27-§30)."""

from app.kernel.confidence import ENGINE_VERSION, EvidenceFact, compute_score


def _ev(id, type="SOURCE_CODE", relation="supports", lineage=None, created_by="agent:a",
        origin="agent"):
    return EvidenceFact(
        id=id,
        type=type,
        relation=relation,
        lineage=lineage or f"file:{id}",
        created_by=created_by,
        origin=origin,
    )


def test_sem_evidencia_score_zero():
    r = compute_score([])
    assert r.score == 0.0
    assert r.engine_version == ENGINE_VERSION


def test_todos_os_sinais_do_prd_no_breakdown():
    r = compute_score([_ev("e1")])
    nomes = {s.name for s in r.signals}
    assert nomes == {
        "number_of_independent_evidence",
        "evidence_type_diversity",
        "test_support",
        "runtime_support",
        "documentation_support",
        "human_support",
        "source_consistency",
        "conflict_presence",
        "duplicate_agreement",
        "agent_agreement",
        "rule_complexity",
        "inference_distance",
    }


def test_score_e_a_soma_das_contribuicoes():
    r = compute_score([_ev("e1"), _ev("e2", type="TEST"), _ev("e3", type="DOCUMENT")])
    assert r.score == round(sum(s.contribution for s in r.signals), 4)


def test_independencia_por_linhagem():
    # §29: teste que mocka o código de produção (mesma linhagem) vale menos
    mesma = compute_score(
        [_ev("e1", lineage="source:X"), _ev("e2", type="TEST", lineage="source:X")]
    )
    indep = compute_score(
        [_ev("e1", lineage="source:X"), _ev("e2", type="TEST", lineage="source:Y")]
    )
    assert indep.score > mesma.score


def test_evidencia_contraditoria_penaliza():
    base = [_ev("e1"), _ev("e2", type="TEST")]
    com_conflito = base + [_ev("e3", type="TEST", relation="contradicts")]
    assert compute_score(com_conflito).score < compute_score(base).score


def test_confirmacao_humana_aumenta():
    base = [_ev("e1")]
    com_humano = base + [_ev("e2", type="DOMAIN_EXPERT", origin="human", created_by="ana@x.com")]
    assert compute_score(com_humano).score > compute_score(base).score


def test_concordancia_de_agentes_exige_dois_distintos():
    um = compute_score(
        [_ev("e1", created_by="agent:a"), _ev("e2", type="TEST", created_by="agent:a")]
    )
    dois = compute_score(
        [_ev("e1", created_by="agent:a"), _ev("e2", type="TEST", created_by="agent:b")]
    )
    assert dois.score > um.score


def test_determinismo():
    facts = [_ev("e1"), _ev("e2", type="TEST"), _ev("e3", type="DOCUMENT")]
    assert compute_score(facts) == compute_score(facts)


def test_caso_forte_ultrapassa_90():
    # código + teste + doc + runtime, todos independentes (§99: caminho automático)
    facts = [
        _ev("e1", type="SOURCE_CODE", lineage="a"),
        _ev("e2", type="TEST", lineage="b", created_by="agent:b"),
        _ev("e3", type="DOCUMENT", lineage="c"),
        _ev("e4", type="RUNTIME", lineage="d"),
    ]
    assert compute_score(facts).score >= 0.90


def test_explicacao_no_formato_do_prd():
    linhas = compute_score([_ev("e1")]).explanation_lines()
    assert any(linha.startswith("+") for linha in linhas)
    assert any(linha.startswith("-") or linha.startswith("·") for linha in linhas)
