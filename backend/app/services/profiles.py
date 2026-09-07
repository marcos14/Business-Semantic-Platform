"""Perfil de evidência por domain (dado), resolvido para os pesos do engine (código versionado).

O perfil é escolhido por domain (`domains.evidence_profile`); sem escolha, vale o padrão da
configuração (`EVIDENCE_PROFILE`). O nome do perfil fica gravado em cada score, então o
histórico de confiança continua explicável mesmo depois de trocar o perfil.
"""

from sqlalchemy.orm import Session

from app.config import settings
from app.kernel.confidence import PROFILES, EvidenceProfile, get_profile
from app.models.auth import Domain


def profile_names() -> list[str]:
    return sorted(PROFILES)


def profile_for_domain(db: Session, domain: str | None) -> EvidenceProfile:
    nome = None
    if domain:
        d = db.get(Domain, domain)
        if d is not None and d.evidence_profile:
            nome = d.evidence_profile
    return get_profile(nome or settings.evidence_profile)


def profile_as_dict(p: EvidenceProfile) -> dict:
    return {
        "name": p.name,
        "site_weights": list(p.site_weights),
        "same_file_weights": list(p.same_file_weights),
        "lineage_cap": p.lineage_cap,
        "type_diversity_step": p.type_diversity_step,
        "type_diversity_cap": p.type_diversity_cap,
        "mechanism_step": p.mechanism_step,
        "mechanism_cap": p.mechanism_cap,
        "test_support": p.test_support,
        "runtime_support": p.runtime_support,
        "documentation_support": p.documentation_support,
        "database_support": p.database_support,
        "reachability": p.reachability,
        "human_support": p.human_support,
        "agent_agreement": p.agent_agreement,
        "source_consistency": p.source_consistency,
        "rule_complexity_penalty": p.rule_complexity_penalty,
        "conflict_penalty": p.conflict_penalty,
        "document_contradiction": p.document_contradiction,
        "document_divergence_penalty": p.document_divergence_penalty,
    }
