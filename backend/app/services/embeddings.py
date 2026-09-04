"""Recuperação e deduplicação semântica de atoms via pgvector.

- `ensure_atom_embeddings`: garante vetor para os atoms de negócio de um domain (backfill
  incremental, em lotes; roda antes de cada turno dirigido e pela CLI).
- `similar_atoms`: top-k por cosseno, filtrando domain/capability e status.
- `embed_texts`: atalho para o provider (None quando embeddings estão desligados).
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.kernel.ir.envelope import AtomKind, LifecycleStatus
from app.llm.embeddings import get_provider, text_hash
from app.models.embeddings import AtomEmbedding
from app.models.knowledge import KnowledgeAtom

log = logging.getLogger(__name__)

# Só conhecimento de negócio entra na recuperação (questions/conflicts são metadados).
BUSINESS_KINDS = [
    str(k) for k in (
        AtomKind.RULE, AtomKind.INVARIANT, AtomKind.DECISION,
        AtomKind.STATE, AtomKind.SCENARIO, AtomKind.CONCEPT,
    )
]
EXCLUDED_STATUS = [str(LifecycleStatus.REJECTED), str(LifecycleStatus.SUPERSEDED)]


def atom_text(atom: KnowledgeAtom) -> str:
    """Texto embedado: a afirmação de negócio (ou a descrição/título quando não há)."""
    body = atom.body or {}
    statement = body.get("statement")
    if not statement and atom.kind == str(AtomKind.DECISION):
        statement = f"{'; '.join(body.get('inputs', []))} → {body.get('output', '')}"
    if not statement and atom.kind == str(AtomKind.SCENARIO):
        g = (body.get("given") or {}).get("description", "")
        w = (body.get("when") or {}).get("description", "")
        t = (body.get("then") or {}).get("description", "")
        statement = f"Dado {g}, quando {w}, então {t}"
    base = statement or atom.description or ""
    return f"{atom.title}. {base}".strip()


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    provider = get_provider()
    if provider is None or not texts:
        return None
    try:
        return provider.embed(texts)
    except Exception:
        log.warning("embeddings indisponíveis neste run (segue sem recuperação vetorial)",
                    exc_info=True)
        return None


def store_embedding(db: Session, atom_id: str, texto: str, vector: list[float]) -> None:
    provider = get_provider()
    modelo = provider.model if provider else "unknown"
    row = db.get(AtomEmbedding, atom_id)
    if row is None:
        db.add(AtomEmbedding(atom_id=atom_id, model=modelo, text_hash=text_hash(texto),
                             embedding=vector))
    else:
        row.model, row.text_hash, row.embedding = modelo, text_hash(texto), vector
        row.updated_at = datetime.now(UTC)


def ensure_atom_embeddings(db: Session, *, domain: str | None = None, limit: int = 500) -> int:
    """Embeda atoms de negócio sem vetor (ou com texto/modelo mudado). Devolve quantos."""
    provider = get_provider()
    if provider is None:
        return 0
    stmt = (
        select(KnowledgeAtom, AtomEmbedding)
        .outerjoin(AtomEmbedding, AtomEmbedding.atom_id == KnowledgeAtom.id)
        .where(KnowledgeAtom.kind.in_(BUSINESS_KINDS))
    )
    if domain:
        stmt = stmt.where(KnowledgeAtom.domain == domain)
    pendentes: list[tuple[KnowledgeAtom, str]] = []
    for atom, emb in db.execute(stmt).all():
        texto = atom_text(atom)
        if emb is None or emb.model != provider.model or emb.text_hash != text_hash(texto):
            pendentes.append((atom, texto))
        if len(pendentes) >= limit:
            break
    if not pendentes:
        return 0
    vetores = embed_texts([t for _, t in pendentes])
    if vetores is None:
        return 0
    for (atom, texto), vec in zip(pendentes, vetores, strict=True):
        store_embedding(db, atom.id, texto, vec)
    db.flush()
    return len(pendentes)


def similar_atoms(
    db: Session,
    vector: list[float],
    *,
    domain: str,
    capability: str | None = None,
    k: int | None = None,
    min_similarity: float = 0.0,
    exclude_ids: set[str] | None = None,
) -> list[tuple[KnowledgeAtom, float]]:
    """Atoms mais próximos (cosseno) no domain; com capability, ela vem primeiro e o
    restante do domain completa a lista."""
    k = k or settings.retrieval_top_k
    dist = AtomEmbedding.embedding.cosine_distance(vector)
    stmt = (
        select(KnowledgeAtom, dist.label("dist"))
        .join(AtomEmbedding, AtomEmbedding.atom_id == KnowledgeAtom.id)
        .where(
            KnowledgeAtom.domain == domain,
            KnowledgeAtom.kind.in_(BUSINESS_KINDS),
            KnowledgeAtom.status.not_in(EXCLUDED_STATUS),
        )
        .order_by(dist)
        .limit(k * 3 if capability else k)
    )
    rows = db.execute(stmt).all()
    saida = []
    for atom, d in rows:
        if exclude_ids and atom.id in exclude_ids:
            continue
        sim = 1.0 - float(d)
        if sim < min_similarity:
            continue
        saida.append((atom, sim))
    if capability:
        # prioriza a capability alvo mantendo a ordem por similaridade dentro de cada grupo
        mesma = [x for x in saida if x[0].capability == capability]
        outras = [x for x in saida if x[0].capability != capability]
        saida = (mesma + outras)[:k]
    return saida[:k]
