"""Confidence Engine v1 (PRD §27-§30) — função pura, determinística e versionada.

O score NUNCA vem de LLM: é calculado sobre fatos (evidence) com pesos
explícitos. Cada sinal do §28 aparece no breakdown com sua contribuição —
mesmo os neutros na v1 — para o score ser sempre explicável (P4, §30).
Os pesos são hipóteses iniciais, recalibradas na Fase 7 (§119); mudanças de
fórmula geram nova ENGINE_VERSION e nunca reescrevem scores históricos.
"""

from dataclasses import dataclass

from app.kernel.ir.envelope import EvidenceRelation, EvidenceType, Origin

ENGINE_VERSION = "v1"


@dataclass(frozen=True)
class EvidenceFact:
    """Projeção de uma evidence vinculada ao atom, com linhagem de origem (§29)."""

    id: str
    type: str
    relation: str  # supports | contradicts
    lineage: str  # evidências com a mesma linhagem NÃO são independentes
    created_by: str
    origin: str


@dataclass(frozen=True)
class SignalResult:
    name: str
    value: float
    contribution: float
    explanation: str


@dataclass(frozen=True)
class ScoreResult:
    score: float
    engine_version: str
    signals: tuple[SignalResult, ...]

    def explanation_lines(self) -> list[str]:
        """Formato do §30: '+ Source code support', '- No runtime evidence'."""
        lines = []
        for s in self.signals:
            sinal = "+" if s.contribution > 0 else ("-" if s.contribution < 0 else "·")
            lines.append(f"{sinal} {s.explanation} ({s.contribution:+.2f})")
        return lines


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, round(x, 4)))


def compute_score(evidence: list[EvidenceFact], body_size: int = 0) -> ScoreResult:
    sup = [e for e in evidence if e.relation == EvidenceRelation.SUPPORTS]
    con = [e for e in evidence if e.relation == EvidenceRelation.CONTRADICTS]
    groups = {e.lineage for e in sup}
    types = {e.type for e in sup}
    agentes = {e.created_by for e in sup if e.origin == Origin.AGENT}

    signals: list[SignalResult] = []

    def add(name: str, value: float, contribution: float, explanation: str) -> None:
        signals.append(SignalResult(name, value, round(contribution, 4), explanation))

    n_groups = len(groups)
    add(
        "number_of_independent_evidence",
        n_groups,
        min(0.20 * n_groups, 0.60),
        f"{n_groups} linhagem(ns) independente(s) de evidência",
    )
    n_types = len(types)
    add(
        "evidence_type_diversity",
        n_types,
        min(0.05 * max(n_types - 1, 0), 0.15),
        f"{n_types} tipo(s) distinto(s) de evidência",
    )
    add(
        "test_support",
        1 if EvidenceType.TEST in types else 0,
        0.08 if EvidenceType.TEST in types else 0.0,
        "suporte de teste automatizado" if EvidenceType.TEST in types else "sem suporte de teste",
    )
    add(
        "runtime_support",
        1 if EvidenceType.RUNTIME in types else 0,
        0.05 if EvidenceType.RUNTIME in types else 0.0,
        "suporte de runtime" if EvidenceType.RUNTIME in types else "sem evidência de runtime",
    )
    add(
        "documentation_support",
        1 if EvidenceType.DOCUMENT in types else 0,
        0.05 if EvidenceType.DOCUMENT in types else 0.0,
        "suporte de documentação"
        if EvidenceType.DOCUMENT in types
        else "sem suporte de documentação",
    )
    humano = bool({EvidenceType.HUMAN_REVIEW, EvidenceType.DOMAIN_EXPERT} & types)
    add(
        "human_support",
        1 if humano else 0,
        0.15 if humano else 0.0,
        "confirmação humana registrada" if humano else "sem confirmação humana",
    )
    add(
        "agent_agreement",
        len(agentes),
        0.05 if len(agentes) >= 2 else 0.0,
        f"{len(agentes)} agente(s) distinto(s) sustentam a afirmação",
    )
    # Sinais neutros na v1 — declarados para o breakdown ser completo (§28)
    add("source_consistency", 0, 0.0, "consistência entre fontes não modelada na v1")
    add("duplicate_agreement", 0, 0.0, "concordância de duplicatas não modelada na v1")
    add("inference_distance", 0, 0.0, "distância de inferência não modelada na v1")
    complexa = body_size > 600
    add(
        "rule_complexity",
        body_size,
        -0.05 if complexa else 0.0,
        "regra extensa/composta (preferir decomposição §47)" if complexa else "complexidade baixa",
    )
    add(
        "conflict_presence",
        len(con),
        -0.30 if con else 0.0,
        f"{len(con)} evidência(s) contraditória(s)" if con else "sem evidência contraditória",
    )

    total = _clamp(sum(s.contribution for s in signals))
    return ScoreResult(score=total, engine_version=ENGINE_VERSION, signals=tuple(signals))
