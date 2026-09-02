"""Consumo do conhecimento (PRD §52-§55, §61-§68, §97).

Search, explorer, context packages, projeções e graph.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.kernel.ir.envelope import (
    AtomKind,
    Classification,
    LifecycleStatus,
    Origin,
    RiskLevel,
)
from app.models.auth import Capability, Domain, User
from app.models.knowledge import KnowledgeAtom
from app.services import context as ctx
from app.services import graph as gsvc
from app.services import knowledge as ksvc
from app.services import projections as proj

search_router = APIRouter(prefix="/search", tags=["consume"])
explorer_router = APIRouter(prefix="/explorer", tags=["consume"])
context_router = APIRouter(prefix="/context", tags=["consume"])
projections_router = APIRouter(prefix="/projections", tags=["consume"])
graph_router = APIRouter(prefix="/graph", tags=["consume"])


def _hit(a: KnowledgeAtom, source: str, rank: float) -> dict:
    return {
        "id": a.id,
        "kind": a.kind,
        "title": a.title,
        "statement": (a.body or {}).get("statement"),
        "domain": a.domain,
        "capability": a.capability,
        "status": a.status,
        "classification": a.classification,
        "confidence": a.confidence,
        "risk": a.risk,
        "match": source,  # fulltext | fuzzy
        "rank": round(float(rank), 4),
    }


@search_router.get("")
def search(
    q: str = Query(min_length=2),
    domain: str | None = None,
    capability: str | None = None,
    status_: LifecycleStatus | None = Query(default=None, alias="status"),
    kind: AtomKind | None = None,
    classification: Classification | None = None,
    risk: RiskLevel | None = None,
    origin: Origin | None = None,
    created_by: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    """§53: full-text (tsvector) + fallback fuzzy (trigram) com todos os filtros."""

    def _filtrar(stmt):
        if domain:
            stmt = stmt.where(KnowledgeAtom.domain == domain)
        if capability:
            stmt = stmt.where(KnowledgeAtom.capability == capability)
        if status_:
            stmt = stmt.where(KnowledgeAtom.status == str(status_))
        if kind:
            stmt = stmt.where(KnowledgeAtom.kind == str(kind))
        if classification:
            stmt = stmt.where(KnowledgeAtom.classification == str(classification))
        if risk:
            stmt = stmt.where(KnowledgeAtom.risk == str(risk))
        if origin:
            stmt = stmt.where(KnowledgeAtom.origin == str(origin))
        if created_by:
            stmt = stmt.where(KnowledgeAtom.created_by == created_by)
        if min_confidence is not None:
            stmt = stmt.where(KnowledgeAtom.confidence >= min_confidence)
        return stmt

    tsq = func.websearch_to_tsquery("portuguese", q)
    rank = func.ts_rank(KnowledgeAtom.search_vector, tsq)
    fts = db.execute(
        _filtrar(
            select(KnowledgeAtom, rank).where(KnowledgeAtom.search_vector.op("@@")(tsq))
        )
        .order_by(rank.desc())
        .limit(limit)
    ).all()
    hits = [_hit(a, "fulltext", r) for a, r in fts]
    encontrados = {h["id"] for h in hits}

    if len(hits) < limit:
        sim = func.similarity(KnowledgeAtom.title, q)
        fuzzy = db.execute(
            _filtrar(select(KnowledgeAtom, sim).where(sim > 0.25))
            .order_by(sim.desc())
            .limit(limit - len(hits))
        ).all()
        hits += [_hit(a, "fuzzy", r) for a, r in fuzzy if a.id not in encontrados]

    return {"query": q, "total": len(hits), "items": hits}


@explorer_router.get("")
def explorer_tree(
    db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> list[dict]:
    """§52: Domain → Capability com contagens por kind e canonical."""
    contagens = db.execute(
        select(
            KnowledgeAtom.domain,
            KnowledgeAtom.capability,
            KnowledgeAtom.kind,
            KnowledgeAtom.status,
            func.count(),
        ).group_by(
            KnowledgeAtom.domain, KnowledgeAtom.capability, KnowledgeAtom.kind, KnowledgeAtom.status
        )
    ).all()
    caps = {c.slug: c for c in db.scalars(select(Capability))}
    arvore: dict[str, dict] = {}
    for d in db.scalars(select(Domain).order_by(Domain.slug)):
        arvore[d.slug] = {"slug": d.slug, "name": d.name, "capabilities": {}}
    for dom, cap, kind, status, n in contagens:
        no_dom = arvore.setdefault(dom, {"slug": dom, "name": dom, "capabilities": {}})
        chave = cap or "_global"
        no_cap = no_dom["capabilities"].setdefault(
            chave,
            {
                "slug": chave,
                "name": caps[cap].name if cap in caps else chave,
                "by_kind": {},
                "canonical": 0,
                "total": 0,
            },
        )
        no_cap["by_kind"][kind] = no_cap["by_kind"].get(kind, 0) + n
        no_cap["total"] += n
        if status == str(LifecycleStatus.CANONICAL):
            no_cap["canonical"] += n
    return [
        {**d, "capabilities": sorted(d["capabilities"].values(), key=lambda c: c["slug"])}
        for d in arvore.values()
    ]


@explorer_router.get("/{domain}/{capability}")
def explorer_capability(
    domain: str,
    capability: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    atoms = db.scalars(
        select(KnowledgeAtom)
        .where(KnowledgeAtom.domain == domain, KnowledgeAtom.capability == capability)
        .order_by(KnowledgeAtom.kind, KnowledgeAtom.id)
    ).all()
    grupos: dict[str, list[dict]] = {}
    for a in atoms:
        grupos.setdefault(a.kind, []).append(
            {
                "id": a.id,
                "title": a.title,
                "status": a.status,
                "confidence": a.confidence,
                "risk": a.risk,
                "classification": a.classification,
                "centrality": a.centrality,
            }
        )
    return {"domain": domain, "capability": capability, "kinds": grupos}


@context_router.get("")
def context_package(
    capability: str,
    task: str | None = None,
    include_candidates: bool = False,
    format: str = Query(default="json", pattern="^(json|markdown)$"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """§61-§63 (AC-CTX-01..03): por padrão só canonical; candidates só explícitos."""
    package = ctx.build_package(
        db, capability=capability, task=task, include_candidates=include_candidates
    )
    if format == "markdown":
        return PlainTextResponse(ctx.to_markdown(package), media_type="text/markdown")
    return package


@projections_router.get("/bdd", response_class=PlainTextResponse)
def bdd_feature(
    capability: str,
    canonical_only: bool = True,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> str:
    return proj.feature_for_capability(db, capability, canonical_only=canonical_only)


@projections_router.get("/bdd/{atom_id}", response_class=PlainTextResponse)
def bdd_scenario(
    atom_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> str:
    return proj.gherkin_for_scenario(ksvc.get_atom(db, atom_id))


@projections_router.get("/decision-table/{atom_id}")
def decision_table(
    atom_id: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> dict:
    return proj.decision_table(ksvc.get_atom(db, atom_id))


@projections_router.get("/state-machine")
def state_machine(
    capability: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> dict:
    return proj.state_machine(db, capability)


@projections_router.get("/markdown", response_class=PlainTextResponse)
def markdown_doc(
    capability: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)
) -> str:
    return proj.markdown_doc(db, capability)


@graph_router.get("")
def graph_neighborhood(
    atom_id: str,
    depth: int = Query(default=2, ge=1, le=4),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    return gsvc.neighborhood(db, atom_id, depth=depth)
