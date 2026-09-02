"""Knowledge Decomposition (PRD §47): o agente SUGERE, o owner decide (§43 Split rule)."""

import json

from sqlalchemy.orm import Session

from app.kernel.errors import KernelError
from app.kernel.ir.envelope import (
    AtomKind,
    EvidenceType,
    LifecycleStatus,
    Origin,
    RelationType,
)
from app.llm import provider as llm
from app.models.auth import User
from app.services import knowledge as ksvc

_SUGGEST_SYSTEM = (
    "Você decompõe regras de negócio compostas em regras pequenas e autocontidas "
    "(princípio: prefer small composable rules). Dada uma regra, proponha de 2 a 5 "
    "sub-regras que juntas cubram exatamente o comportamento original, sem inventar "
    "comportamento novo. Responda SOMENTE JSON: "
    '{"rules": [{"title": "...", "statement": "..."}]}. '
    "Se a regra já for atômica, devolva lista vazia."
)


def suggest(atom, llm_provider: llm.LLMProvider | None = None) -> list[dict]:
    statement = (atom.body or {}).get("statement") or atom.title
    resposta = (llm_provider or llm.get_provider()).complete(
        system=_SUGGEST_SYSTEM,
        user=f"Regra: {atom.title}\n\n{statement}",
        max_tokens=1500,
    )
    ini, fim = resposta.find("{"), resposta.rfind("}")
    if ini < 0 or fim <= ini:
        raise KernelError("Sugestão de decomposição sem JSON reconhecível")
    regras = json.loads(resposta[ini : fim + 1]).get("rules", [])
    return [r for r in regras if r.get("title") and r.get("statement")]


def apply(
    db: Session,
    atom_id: str,
    owner: User,
    *,
    rules: list[dict],
    reason: str,
    expected_lock_version: int,
) -> list[str]:
    """Aplica o split (§43/§47): novas rules SUPERSEDES a original; original REJECTED.

    Rule canonical não é decomposta por aqui — o caminho é supersede (§72).
    """
    original = ksvc.get_atom(db, atom_id)
    if original.status in (str(LifecycleStatus.CANONICAL), str(LifecycleStatus.SUPERSEDED)):
        raise KernelError("Rule canonical é decomposta via new-version/supersede (§71-§72)")
    if original.lock_version != expected_lock_version:
        from app.kernel.errors import StaleVersionError

        raise StaleVersionError(
            f"Versão desatualizada: esperada {expected_lock_version}, "
            f"atual {original.lock_version}"
        )
    if len(rules) < 2:
        raise KernelError("Decomposição exige pelo menos 2 sub-regras")

    criadas: list[str] = []
    for r in rules:
        nova = ksvc.create_candidate(
            db, actor=owner.email, origin=Origin.HUMAN, kind=AtomKind.RULE,
            title=r["title"], domain=original.domain, capability=original.capability,
            scope=r.get("scope") or original.scope,
            body={"statement": r["statement"]},
            evidence=[{
                "type": EvidenceType.HUMAN_REVIEW,
                "summary": f"Decomposição de {original.id} pelo owner: {reason}",
                "metadata": {"reviewer": owner.email, "decision": "SPLIT_RULE"},
            }],
        )
        db.flush()
        ksvc.add_relation(
            db, actor=owner.email, from_atom=nova.id, to_atom=original.id,
            relation_type=RelationType.SUPERSEDES,
        )
        criadas.append(nova.id)

    original = ksvc.get_atom(db, atom_id)
    if original.status == str(LifecycleStatus.NEEDS_HUMAN_REVIEW):
        original = ksvc.change_status(
            db, atom_id, actor=owner.email, new_status=LifecycleStatus.IN_REVIEW,
            reason="decomposição iniciada", expected_lock_version=original.lock_version,
        )
    ksvc.change_status(
        db, atom_id, actor=owner.email, new_status=LifecycleStatus.REJECTED,
        reason=f"decomposta em {', '.join(criadas)}: {reason}",
        expected_lock_version=original.lock_version,
    )
    return criadas
