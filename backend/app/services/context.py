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
from app.models.knowledge import AtomRelation, KnowledgeAtom

# §63: rótulos de segurança
CANONICAL = "CANONICAL"
PROVISIONAL = "PROVISIONAL"  # faixa intermediária: publicado com rótulo, corrigível
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
    ("events", AtomKind.EVENT),
    ("processes", AtomKind.PROCESS),
    ("exceptions", AtomKind.EXCEPTION),
    ("scenarios", AtomKind.SCENARIO),
    ("messages", AtomKind.MESSAGE),
    ("procedures", AtomKind.PROCEDURE),
]


def _item(a: KnowledgeAtom, label: str, relations: list[dict]) -> dict:
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
        "significance": a.significance,
        "scope": a.scope,
        "effective": a.effective,
        "body": a.body,
        "version": a.version,
        "relations": relations,
        "evidence_summaries": [
            link.evidence.summary
            for link in a.evidence_links
            if link.relation == "supports" and link.evidence.summary
        ],
        "evidence_refs": [
            {
                "id": str(link.evidence.id),
                "type": link.evidence.type,
                "relation": link.relation,
                "summary": link.evidence.summary,
                "location": link.evidence.location,
                "mechanism": (link.evidence.meta or {}).get("mechanism"),
                "source_id": str(link.evidence.source_id) if link.evidence.source_id else None,
            }
            for link in a.evidence_links
        ],
    }


def build_package(
    db: Session,
    *,
    capability: str,
    task: str | None = None,
    include_candidates: bool = False,
    include_provisional: bool = False,
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

    atom_ids = [a.id for a in atoms]
    relation_map: dict[str, list[dict]] = {}
    if atom_ids:
        for rel in db.scalars(
            select(AtomRelation).where(
                AtomRelation.from_atom.in_(atom_ids), AtomRelation.to_atom.in_(atom_ids)
            )
        ):
            payload = {"from": rel.from_atom, "to": rel.to_atom, "type": rel.type}
            relation_map.setdefault(rel.from_atom, []).append(payload)
            relation_map.setdefault(rel.to_atom, []).append(payload)

    package: dict = {
        "capability": {
            "slug": cap.slug,
            "name": cap.name,
            "description": cap.description,
            "domain": cap.domain_slug,
        },
        "task": task,
        "safety_note": (
            "Apenas itens rotulados CANONICAL são regra oficial. PROVISIONAL = publicado "
            "com boa confiança mas ainda não confirmado (pode ser corrigido); OBSERVED = "
            "candidato não aprovado; UNRESOLVED = conflito aberto; UNKNOWN = pergunta sem "
            "resposta. Nunca trate itens não-canonical como verdade (§63)."
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
            package[secao].append(_item(a, CANONICAL, relation_map.get(a.id, [])))
        elif a.status == str(LifecycleStatus.PROVISIONAL):
            if include_provisional or include_candidates:
                package[secao].append(_item(a, PROVISIONAL, relation_map.get(a.id, [])))
        elif include_candidates and a.status not in (
            str(LifecycleStatus.REJECTED),
            str(LifecycleStatus.SUPERSEDED),
        ):
            package[secao].append(_item(a, OBSERVED, relation_map.get(a.id, [])))

    package["stats"] = {
        "canonical": sum(
            1 for s, _ in _KIND_SECTIONS for i in package[s] if i["label"] == CANONICAL
        ),
        "provisional": sum(
            1 for s, _ in _KIND_SECTIONS for i in package[s] if i["label"] == PROVISIONAL
        ),
        "observed": sum(
            1 for s, _ in _KIND_SECTIONS for i in package[s] if i["label"] == OBSERVED
        ),
        "known_conflicts": len(package["known_conflicts"]),
        "open_questions": len(package["open_questions"]),
    }
    return package


def _body_markdown(item: dict) -> list[str]:
    body = item.get("body") or {}
    kind = item.get("kind")
    lines: list[str] = []
    if kind == "concept" and body.get("synonyms"):
        lines.append("*Sinônimos:* " + ", ".join(body["synonyms"]))
    elif kind == "decision":
        lines.append("*Entradas:* " + ", ".join(body.get("inputs", [])))
        lines.append(f"*Saída:* {body.get('output', '—')}")
        for row in (body.get("logic") or {}).get("rows", []):
            lines.append(f"- decisão: `{row}`")
    elif kind == "transition":
        lines.append(
            f"*Transição:* `{body.get('from_state', '—')}` → `{body.get('to_state', '—')}`"
        )
        if body.get("trigger"):
            lines.append(f"*Gatilho:* {body['trigger']}")
        lines.extend(f"- condição: {condition}" for condition in body.get("conditions", []))
    elif kind == "event" and body.get("payload_fields"):
        lines.append("*Payload:* " + ", ".join(body["payload_fields"]))
    elif kind == "process":
        for number, step in enumerate(body.get("steps", []), 1):
            lines.append(f"{number}. {step.get('title') or step.get('description') or step}")
    elif kind == "exception":
        lines.append(f"*Aplica-se a:* `{body.get('applies_to', '—')}`")
        lines.append(f"*Condição:* {body.get('condition', '—')}")
    elif kind == "scenario":
        for prefix, key in (("Dado", "given"), ("Quando", "when"), ("Então", "then")):
            value = body.get(key) or {}
            lines.append(f"- **{prefix}:** {value.get('description') or value}")
    elif kind == "message":
        lines.append(f"*Mensagem:* {body.get('text', '—')}")
        if body.get("code"):
            lines.append(f"*Código:* `{body['code']}`")
        if body.get("meaning"):
            lines.append(f"*Significado:* {body['meaning']}")
    elif kind == "procedure":
        lines.append(f"*Objetivo:* {body.get('goal', '—')}")
        lines.extend(f"- pré-condição: {p}" for p in body.get("prerequisites", []))
        for step in sorted(body.get("steps", []), key=lambda s: s.get("order", 0)):
            expected = f" → {step['expected_result']}" if step.get("expected_result") else ""
            lines.append(f"{step.get('order', '-')}. {step.get('action', '')}{expected}")
        lines.extend(f"- escalar quando: {e}" for e in body.get("escalation_conditions", []))
    return lines


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
    if cap.get("description"):
        linhas += [cap["description"], ""]
    titulos = {
        "concepts": "Conceitos",
        "rules": "Regras",
        "decisions": "Decisões",
        "invariants": "Invariantes",
        "states": "Estados",
        "transitions": "Transições",
        "events": "Eventos",
        "processes": "Processos",
        "exceptions": "Exceções",
        "scenarios": "Cenários",
        "messages": "Mensagens",
        "procedures": "Procedimentos",
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
            linhas.extend(_body_markdown(i))
            if i.get("scope"):
                linhas.append(f"*Escopo:* `{i['scope']}`")
            if i.get("effective"):
                linhas.append(f"*Vigência:* `{i['effective']}`")
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
