"""Confidence Engine v2 (PRD §27-§30) — função pura, determinística e versionada.

O score NUNCA vem de LLM: é calculado sobre fatos (evidence) com pesos
explícitos. Cada sinal do §28 aparece no breakdown com sua contribuição —
mesmo os neutros — para o score ser sempre explicável (P4, §30).

v2 (2026-09):
- Pesos vêm de um PERFIL DE EVIDÊNCIA (dado escolhido por domain): ambientes diferentes
  justificam crenças diferentes sobre a mesma evidência (um ERP de 23 anos sem documentação
  não é um sistema novo com testes). O perfil usado fica gravado em cada score.
- Independência por SÍTIO (arquivo + rotina envolvente), não por arquivo: em legados onde um
  módulo mora inteiro numa unit, a corroboração real está em várias rotinas do mesmo arquivo.
  Sítios no mesmo arquivo valem com desconto; arquivos distintos valem cheio.
- Sinais novos: `mechanism_diversity` (validação + mensagem + SQL dizendo a mesma coisa),
  `database_support`, `reachability` (o trecho está vivo), `source_consistency` (tipos de
  fonte distintos de Sources distintas concordam) e `document_divergence` (documento velho
  contradizendo código, quando o perfil não trata isso como conflito).

Mudanças de fórmula geram nova ENGINE_VERSION e nunca reescrevem scores históricos (§27).
"""

from dataclasses import dataclass

from app.kernel.ir.envelope import (
    EvidenceMechanism,
    EvidenceRelation,
    EvidenceType,
    Origin,
)

ENGINE_VERSION = "v2"


@dataclass(frozen=True)
class EvidenceProfile:
    """Pesos do engine. Hipóteses a calibrar com uso humano real (PRD §119)."""

    name: str
    # 1º, 2º, 3º... sítio em ARQUIVOS (linhagens) distintos; o último valor repete.
    site_weights: tuple[float, ...]
    # 2º, 3º... sítio no MESMO arquivo (rotina distinta); além da tupla, não soma.
    same_file_weights: tuple[float, ...]
    lineage_cap: float
    type_diversity_step: float
    type_diversity_cap: float
    mechanism_step: float
    mechanism_cap: float
    test_support: float
    runtime_support: float
    documentation_support: float
    database_support: float
    reachability: float
    human_support: float
    agent_agreement: float
    source_consistency: float
    rule_complexity_penalty: float
    conflict_penalty: float
    # "conflict": contradição vinda de documento é conflito como qualquer outra;
    # "divergence": documento velho contradizendo código vira divergência leve (question).
    document_contradiction: str
    document_divergence_penalty: float

    @property
    def max_sites_per_file(self) -> int:
        return 1 + len(self.same_file_weights)

    def treats_document_as_divergence(self) -> bool:
        return self.document_contradiction == "divergence"


DEFAULT_PROFILE = EvidenceProfile(
    name="default",
    site_weights=(0.20,),
    same_file_weights=(0.10, 0.05),
    lineage_cap=0.60,
    type_diversity_step=0.05,
    type_diversity_cap=0.15,
    mechanism_step=0.0,
    mechanism_cap=0.0,
    test_support=0.08,
    runtime_support=0.05,
    documentation_support=0.05,
    database_support=0.05,
    reachability=0.05,
    human_support=0.15,
    agent_agreement=0.05,
    source_consistency=0.10,
    rule_complexity_penalty=-0.05,
    conflict_penalty=-0.30,
    document_contradiction="conflict",
    document_divergence_penalty=0.0,
)

# Legado hostil: sem documentação canônica, testes recentes e pouco confiáveis. O código é a
# única fonte que reflete produção; o schema do banco vem em segundo; docs são pista.
LEGACY_HOSTILE_PROFILE = EvidenceProfile(
    name="legacy-hostile",
    site_weights=(0.45, 0.25, 0.10),
    same_file_weights=(0.15, 0.10),
    lineage_cap=0.80,
    type_diversity_step=0.0,
    type_diversity_cap=0.0,
    mechanism_step=0.05,
    mechanism_cap=0.10,
    test_support=0.05,
    runtime_support=0.05,
    documentation_support=0.03,
    database_support=0.08,
    reachability=0.10,
    human_support=0.15,
    agent_agreement=0.05,
    source_consistency=0.10,
    rule_complexity_penalty=-0.05,
    conflict_penalty=-0.30,
    document_contradiction="divergence",
    document_divergence_penalty=-0.05,
)

PROFILES: dict[str, EvidenceProfile] = {
    p.name: p for p in (DEFAULT_PROFILE, LEGACY_HOSTILE_PROFILE)
}


def get_profile(name: str | None) -> EvidenceProfile:
    return PROFILES.get(name or DEFAULT_PROFILE.name, DEFAULT_PROFILE)


@dataclass(frozen=True)
class EvidenceFact:
    """Projeção de uma evidence vinculada ao atom, com linhagem de origem (§29).

    `lineage` continua sendo a chave de independência grossa (arquivo/source/evidence);
    `file`/`symbol`/linhas refinam para o sítio (rotina) quando existem.
    """

    id: str
    type: str
    relation: str  # supports | contradicts
    lineage: str  # evidências com a mesma linhagem NÃO são independentes
    created_by: str
    origin: str
    file: str | None = None
    symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    mechanism: str | None = None
    source_id: str | None = None


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
    profile: str = DEFAULT_PROFILE.name

    def explanation_lines(self) -> list[str]:
        """Formato do §30: '+ Source code support', '- No runtime evidence'."""
        lines = []
        for s in self.signals:
            sinal = "+" if s.contribution > 0 else ("-" if s.contribution < 0 else "·")
            lines.append(f"{sinal} {s.explanation} ({s.contribution:+.2f})")
        return lines


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, round(x, 4)))


def _merge_ranges(faixas: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Faixas de linhas sobrepostas (ou encostadas) são o mesmo sítio."""
    saida: list[tuple[int, int]] = []
    for ini, fim in sorted(faixas):
        if saida and ini <= saida[-1][1] + 1:
            a, b = saida[-1]
            saida[-1] = (a, max(b, fim))
        else:
            saida.append((ini, fim))
    return saida


def sites_by_lineage(facts: list[EvidenceFact]) -> dict[str, list[str]]:
    """Agrupa evidências de suporte em linhagem (arquivo) → sítios distintos (rotinas).

    - Sem arquivo: a própria `lineage` é o sítio (source inteira, evidência humana etc.).
    - Com símbolo (rotina envolvente): um sítio por símbolo.
    - Sem símbolo: faixas de linhas sobrepostas colapsam num sítio; faixas separadas contam
      como sítios distintos do mesmo arquivo.
    """
    por_linhagem: dict[str, list[EvidenceFact]] = {}
    for e in facts:
        por_linhagem.setdefault(e.lineage, []).append(e)
    saida: dict[str, list[str]] = {}
    for linhagem, itens in por_linhagem.items():
        sitios: list[str] = []
        faixas: list[tuple[int, int]] = []
        for e in itens:
            if e.file is None:
                if linhagem not in sitios:
                    sitios.append(linhagem)
            elif e.symbol:
                chave = f"sym:{e.symbol.strip().lower()}"
                if chave not in sitios:
                    sitios.append(chave)
            elif e.start_line is not None and e.end_line is not None:
                faixas.append((int(e.start_line), int(e.end_line)))
            elif "file" not in sitios:
                sitios.append("file")
        sitios += [f"lines:{a}-{b}" for a, b in _merge_ranges(faixas)]
        saida[linhagem] = sitios or ["file"]
    return saida


def compute_score(
    evidence: list[EvidenceFact],
    body_size: int = 0,
    profile: EvidenceProfile | None = None,
) -> ScoreResult:
    p = profile or DEFAULT_PROFILE
    reach_mech = str(EvidenceMechanism.REACHABILITY)
    sup_all = [e for e in evidence if e.relation == EvidenceRelation.SUPPORTS]
    # prova de alcançabilidade não é sítio da regra
    sup = [e for e in sup_all if (e.mechanism or "").upper() != reach_mech]
    alcancavel = [e for e in sup_all if (e.mechanism or "").upper() == reach_mech]
    con_all = [e for e in evidence if e.relation == EvidenceRelation.CONTRADICTS]
    if p.treats_document_as_divergence():
        con = [c for c in con_all if c.type != EvidenceType.DOCUMENT]
        doc_div = [c for c in con_all if c.type == EvidenceType.DOCUMENT]
    else:
        con, doc_div = con_all, []
    types = {e.type for e in sup}
    agentes = {e.created_by for e in sup if e.origin == Origin.AGENT}

    signals: list[SignalResult] = []

    def add(name: str, value: float, contribution: float, explanation: str) -> None:
        signals.append(SignalResult(name, value, round(contribution, 4), explanation))

    # --- independência por sítio ---
    sitios = sites_by_lineage(sup)
    n_linhagens = len(sitios)
    contrib = 0.0
    for i in range(n_linhagens):
        contrib += p.site_weights[min(i, len(p.site_weights) - 1)]
    extras = 0
    for lista in sitios.values():
        for j in range(1, min(len(lista), p.max_sites_per_file)):
            contrib += p.same_file_weights[j - 1]
            extras += 1
    contrib = min(contrib, p.lineage_cap)
    explicacao = f"{n_linhagens} linhagem(ns) independente(s) de evidência"
    if extras:
        explicacao += f", {extras} sítio(s) adicional(is) no mesmo arquivo"
    add("number_of_independent_evidence", n_linhagens + extras, contrib, explicacao)

    n_types = len(types)
    add(
        "evidence_type_diversity",
        n_types,
        min(p.type_diversity_step * max(n_types - 1, 0), p.type_diversity_cap),
        f"{n_types} tipo(s) distinto(s) de evidência",
    )
    mecanismos = {
        (e.mechanism or "").upper()
        for e in sup
        if e.mechanism and e.mechanism.upper() != reach_mech
    }
    n_mec = len(mecanismos)
    add(
        "mechanism_diversity",
        n_mec,
        min(p.mechanism_step * max(n_mec - 1, 0), p.mechanism_cap),
        (
            f"{n_mec} mecanismo(s) distinto(s) impõem a regra ({', '.join(sorted(mecanismos))})"
            if n_mec
            else "mecanismo da evidência não informado"
        ),
    )
    add(
        "test_support",
        1 if EvidenceType.TEST in types else 0,
        p.test_support if EvidenceType.TEST in types else 0.0,
        "suporte de teste automatizado" if EvidenceType.TEST in types else "sem suporte de teste",
    )
    add(
        "runtime_support",
        1 if EvidenceType.RUNTIME in types else 0,
        p.runtime_support if EvidenceType.RUNTIME in types else 0.0,
        "suporte de runtime" if EvidenceType.RUNTIME in types else "sem evidência de runtime",
    )
    add(
        "documentation_support",
        1 if EvidenceType.DOCUMENT in types else 0,
        p.documentation_support if EvidenceType.DOCUMENT in types else 0.0,
        "suporte de documentação"
        if EvidenceType.DOCUMENT in types
        else "sem suporte de documentação",
    )
    add(
        "database_support",
        1 if EvidenceType.DATABASE in types else 0,
        p.database_support if EvidenceType.DATABASE in types else 0.0,
        "suporte do schema/banco de dados"
        if EvidenceType.DATABASE in types
        else "sem suporte de banco de dados",
    )
    add(
        "reachability",
        1 if alcancavel else 0,
        p.reachability if alcancavel else 0.0,
        "trecho verificado como alcançável (unit no projeto / rotina chamada)"
        if alcancavel
        else "alcançabilidade do trecho não verificada",
    )
    humano = bool({EvidenceType.HUMAN_REVIEW, EvidenceType.DOMAIN_EXPERT} & types)
    add(
        "human_support",
        1 if humano else 0,
        p.human_support if humano else 0.0,
        "confirmação humana registrada" if humano else "sem confirmação humana",
    )
    add(
        "agent_agreement",
        len(agentes),
        p.agent_agreement if len(agentes) >= 2 else 0.0,
        f"{len(agentes)} agente(s) distinto(s) sustentam a afirmação",
    )
    # consistência entre fontes: tipos distintos vindos de Sources distintas, sem contradição
    com_source = {(e.type, e.source_id) for e in sup if e.source_id}
    tipos_src = {t for t, _ in com_source}
    sources = {s for _, s in com_source}
    consistente = len(tipos_src) >= 2 and len(sources) >= 2 and not con
    add(
        "source_consistency",
        len(sources),
        p.source_consistency if consistente else 0.0,
        (
            f"{len(tipos_src)} tipos de evidência de {len(sources)} fontes distintas concordam"
            if consistente
            else "sem concordância entre fontes distintas"
        ),
    )
    # Sinais neutros — declarados para o breakdown ser completo (§28)
    add("duplicate_agreement", 0, 0.0, "concordância de duplicatas não modelada")
    add("inference_distance", 0, 0.0, "distância de inferência não modelada")
    complexa = body_size > 600
    add(
        "rule_complexity",
        body_size,
        p.rule_complexity_penalty if complexa else 0.0,
        "regra extensa/composta (preferir decomposição §47)" if complexa else "complexidade baixa",
    )
    add(
        "conflict_presence",
        len(con),
        p.conflict_penalty if con else 0.0,
        f"{len(con)} evidência(s) contraditória(s)" if con else "sem evidência contraditória",
    )
    add(
        "document_divergence",
        len(doc_div),
        p.document_divergence_penalty if doc_div else 0.0,
        (
            f"{len(doc_div)} documento(s) divergem do código (documentação tratada como pista)"
            if doc_div
            else "sem divergência documental"
        ),
    )

    total = _clamp(sum(s.contribution for s in signals))
    return ScoreResult(
        score=total, engine_version=ENGINE_VERSION, signals=tuple(signals), profile=p.name
    )
