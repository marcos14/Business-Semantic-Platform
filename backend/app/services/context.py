"""Context Builder (PRD §61-§63): pacotes semânticos para agentes.

Por padrão APENAS canonical (AC-CTX-02); candidates entram só por pedido
explícito, rotulados. Conflitos abertos e questions sempre presentes e
claramente identificados (AC-CTX-03) — Agent Context Safety (§63).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.kernel.errors import NotFoundError
from app.kernel.ir.envelope import AtomKind, LifecycleStatus
from app.models.auth import Capability
from app.models.knowledge import KnowledgeAtom

# §63: rótulos de segurança
CANONICAL = "CANONICAL"
OBSERVED = "OBSERVED"
UNRESOLVED = "UNRESOLVED"
UNKNOWN = "UNKNOWN"

_KIND_SECTIONS = [
    ("concepts", AtomKind.CONCEPT),
    ("rules", AtomKind.RULE),
    ("decisions", AtomKind.DECISION),
    ("invariants", AtomKind.INVARIANT),
    ("states", AtomKind.STATE),
    ("transitions", AtomKind.TRANSITION),
    ("processes", AtomKind.PROCESS),
    ("exceptions", AtomKind.EXCEPTION),
    ("scenarios", AtomKind.SCENARIO),
]


def _item(a: KnowledgeAtom, label: str) -> dict:
    return {
        "id": a.id,
        "label": label,  # §63: nunca tratar tudo como regra oficial
        "kind": a.kind,
        "title": a.title,
        "statement": (a.body or {}).get("statement"),
        "description": a.description,
        "classification": a.classification,
        "confidence": a.confidence,
        "risk": a.risk,
        "scope": a.scope,
        "body": a.body,
        "version": a.version,
        "evidence_summaries": [
            link.evidence.summary
            for link in a.evidence_links
            if link.relation == "supports" and link.evidence.summary
        ],
    }


def build_package(
    db: Session, *, capability: str, task: str | None = None, include_candidates: bool = False
) -> dict:
    cap = db.get(Capability, capability)
    if cap is None:
        raise NotFoundError(f"Capability inexistente: {capability}")

    atoms = list(
        db.scalars(
            select(KnowledgeAtom)
            .where(KnowledgeAtom.capability == capability)
            .options(selectinload(KnowledgeAtom.evidence_links))
            .order_by(KnowledgeAtom.id)
        )
    )

    package: dict = {
        "capability": {"slug": cap.slug, "name": cap.name, "domain": cap.domain_slug},
        "task": task,
        "safety_note": (
            "Apenas itens rotulados CANONICAL são regra oficial. OBSERVED = candidato "
            "não aprovado; UNRESOLVED = conflito aberto; UNKNOWN = pergunta sem resposta. "
            "Nunca trate itens não-canonical como verdade (§63)."
        ),
    }
    for section, _kind in _KIND_SECTIONS:
        package[section] = []
    package["known_conflicts"] = []
    package["open_questions"] = []

    secao_por_kind = {str(k): s for s, k in _KIND_SECTIONS}
    for a in atoms:
        if a.kind == str(AtomKind.CONFLICT):
            body = a.body or {}
            if body.get("state") == "open":
                package["known_conflicts"].append(
                    {
                        "id": a.id,
                        "label": UNRESOLVED,
                        "topic": body.get("topic"),
                        "about": body.get("about"),
                        "assertions": body.get("assertions", []),
                        "reevaluation": body.get("reevaluation", False),
                    }
                )
            continue
        if a.kind == str(AtomKind.QUESTION):
            body = a.body or {}
            if not body.get("answer"):
                package["open_questions"].append(
                    {"id": a.id, "label": UNKNOWN, "question": body.get("question")}
                )
            continue
        secao = secao_por_kind.get(a.kind)
        if secao is None:
            continue
        if a.status == str(LifecycleStatus.CANONICAL):
            package[secao].append(_item(a, CANONICAL))
        elif include_candidates and a.status not in (
            str(LifecycleStatus.REJECTED),
            str(LifecycleStatus.SUPERSEDED),
        ):
            package[secao].append(_item(a, OBSERVED))

    package["stats"] = {
        "canonical": sum(
            1 for s, _ in _KIND_SECTIONS for i in package[s] if i["label"] == CANONICAL
        ),
        "observed": sum(
            1 for s, _ in _KIND_SECTIONS for i in package[s] if i["label"] == OBSERVED
        ),
        "known_conflicts": len(package["known_conflicts"]),
        "open_questions": len(package["open_questions"]),
    }
    return package


def to_markdown(package: dict) -> str:
    cap = package["capability"]
    linhas = [
        f"# Context Package — {cap['name']} ({cap['domain']}/{cap['slug']})",
        "",
        f"> {package['safety_note']}",
        "",
    ]
    if package.get("task"):
        linhas += [f"**Tarefa:** {package['task']}", ""]
    titulos = {
        "concepts": "Conceitos",
        "rules": "Regras",
        "decisions": "Decisões",
        "invariants": "Invariantes",
        "states": "Estados",
        "transitions": "Transições",
        "processes": "Processos",
        "exceptions": "Exceções",
        "scenarios": "Cenários",
    }
    for section, titulo in titulos.items():
        itens = package.get(section) or []
        if not itens:
            continue
        linhas.append(f"## {titulo}")
        for i in itens:
            marca = "" if i["label"] == CANONICAL else f" `[{i['label']}]`"
            linhas.append(f"### {i['title']}{marca}")
            if i.get("statement"):
                linhas.append(i["statement"])
            elif i.get("description"):
                linhas.append(i["description"])
            if i.get("scope"):
                linhas.append(f"*Escopo:* `{i['scope']}`")
            for ev in i.get("evidence_summaries", [])[:3]:
                linhas.append(f"- evidência: {ev}")
            linhas.append("")
    if package["known_conflicts"]:
        linhas.append("## Conflitos conhecidos `[UNRESOLVED]`")
        for c in package["known_conflicts"]:
            linhas.append(f"- **{c['topic']}** ({c['id']})")
        linhas.append("")
    if package["open_questions"]:
        linhas.append("## Perguntas em aberto `[UNKNOWN]`")
        for q in package["open_questions"]:
            linhas.append(f"- {q['question']} ({q['id']})")
        linhas.append("")
    return "\n".join(linhas)
