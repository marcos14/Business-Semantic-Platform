"""Semantic Graph como projeção (PRD §54-§56): vizinhança, impact analysis e centralidade.

O graph NUNCA é source of truth — é derivado de `atom_relations` sob demanda.
"""

import networkx as nx
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.kernel.ir.envelope import RelationType
from app.models.knowledge import AtomRelation, KnowledgeAtom
from app.services import knowledge as ksvc

# §55: direção de PROPAGAÇÃO de impacto por tipo de relação.
# "forward": A --rel--> B implica "mudar A afeta B"; "reverse": implica "mudar B afeta A".
_IMPACT_DIRECTION: dict[str, str] = {
    str(RelationType.DEPENDS_ON): "reverse",  # A depende de B → mudar B afeta A
    str(RelationType.CONSUMES): "reverse",  # A consome B → mudar B afeta A
    str(RelationType.AFFECTS): "forward",
    str(RelationType.GOVERNS): "forward",
    str(RelationType.TRIGGERS): "forward",
    str(RelationType.PRODUCES): "forward",
    str(RelationType.USED_BY): "forward",  # A é usado por B → mudar A afeta B
    str(RelationType.EXEMPLIFIED_BY): "forward",  # mudar a regra afeta o cenário
    # CONTRADICTS/SUPERSEDES não propagam impacto
}


def _domain_relations(db: Session, domain: str) -> list[AtomRelation]:
    ids = select(KnowledgeAtom.id).where(KnowledgeAtom.domain == domain)
    return list(
        db.scalars(
            select(AtomRelation).where(
                or_(AtomRelation.from_atom.in_(ids), AtomRelation.to_atom.in_(ids))
            )
        )
    )


def neighborhood(db: Session, atom_id: str, depth: int = 2, max_nodes: int = 200) -> dict:
    """Vizinhança do atom (§54) até `depth` saltos, em qualquer direção."""
    centro = ksvc.get_atom(db, atom_id)
    rels = _domain_relations(db, centro.domain)
    adj: dict[str, list[tuple[str, str, str]]] = {}
    for r in rels:
        adj.setdefault(r.from_atom, []).append((r.to_atom, r.type, "out"))
        adj.setdefault(r.to_atom, []).append((r.from_atom, r.type, "in"))

    visitados = {atom_id: 0}
    fila = [atom_id]
    while fila and len(visitados) < max_nodes:
        atual = fila.pop(0)
        if visitados[atual] >= depth:
            continue
        for vizinho, _t, _d in adj.get(atual, []):
            if vizinho not in visitados:
                visitados[vizinho] = visitados[atual] + 1
                fila.append(vizinho)

    atoms = {
        a.id: a
        for a in db.scalars(select(KnowledgeAtom).where(KnowledgeAtom.id.in_(visitados)))
    }
    return {
        "center": atom_id,
        "nodes": [
            {
                "id": a.id,
                "kind": a.kind,
                "title": a.title,
                "status": a.status,
                "confidence": a.confidence,
                "distance": visitados[a.id],
            }
            for a in atoms.values()
        ],
        "edges": [
            {"from": r.from_atom, "to": r.to_atom, "type": r.type}
            for r in rels
            if r.from_atom in visitados and r.to_atom in visitados
        ],
    }


def impact(db: Session, atom_id: str, max_depth: int = 6) -> dict:
    """§55: 'What is affected if this changes?' — direto + transitivo, agrupado por kind."""
    origem = ksvc.get_atom(db, atom_id)
    afeta: dict[str, set[str]] = {}
    for r in _domain_relations(db, origem.domain):
        direcao = _IMPACT_DIRECTION.get(r.type)
        if direcao == "forward":
            afeta.setdefault(r.from_atom, set()).add(r.to_atom)
        elif direcao == "reverse":
            afeta.setdefault(r.to_atom, set()).add(r.from_atom)

    nivel = {atom_id: 0}
    fila = [atom_id]
    while fila:
        atual = fila.pop(0)
        if nivel[atual] >= max_depth:
            continue
        for alvo in afeta.get(atual, ()):
            if alvo not in nivel:
                nivel[alvo] = nivel[atual] + 1
                fila.append(alvo)
    nivel.pop(atom_id)

    atoms = {
        a.id: a for a in db.scalars(select(KnowledgeAtom).where(KnowledgeAtom.id.in_(nivel)))
    }
    itens = [
        {
            "id": a.id,
            "kind": a.kind,
            "title": a.title,
            "status": a.status,
            "distance": nivel[a.id],
        }
        for a in sorted(atoms.values(), key=lambda x: (nivel[x.id], x.id))
    ]
    por_kind: dict[str, int] = {}
    for i in itens:
        por_kind[i["kind"]] = por_kind.get(i["kind"], 0) + 1
    return {
        "atom_id": atom_id,
        "direct": [i for i in itens if i["distance"] == 1],
        "transitive": [i for i in itens if i["distance"] > 1],
        "by_kind": dict(sorted(por_kind.items())),
        "total": len(itens),
    }


def compute_centrality(db: Session) -> int:
    """§56: centralidade de grau normalizada 0..1, gravada em atoms.centrality.

    Alimenta a priorização de review (§84): regra usada por dezenas de processos
    fura a fila na frente de regra isolada. Heurística simples por decisão do
    próprio PRD (§56); PageRank/betweenness ficam para quando o graph crescer.
    """
    rels = db.execute(select(AtomRelation.from_atom, AtomRelation.to_atom)).all()
    if not rels:
        return 0
    g = nx.DiGraph()
    g.add_edges_from(rels)
    grau = nx.degree_centrality(g)
    maximo = max(grau.values()) or 1.0
    for atom_id, valor in grau.items():
        db.execute(
            update(KnowledgeAtom)
            .where(KnowledgeAtom.id == atom_id)
            .values(centrality=round(valor / maximo, 4))
        )
    return len(grau)
