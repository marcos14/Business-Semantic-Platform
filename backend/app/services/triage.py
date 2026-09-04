"""Triagem de relevância dos candidates que já esperam revisão humana.

Candidates criados antes da régua (ou por agentes que não a aplicaram) estão em
NEEDS_HUMAN_REVIEW sem `significance`. Um modelo de análise (porta LLMProvider, canal API)
classifica cada um em SYSTEMIC/LOW/MEDIUM/HIGH a partir de título + afirmação; os SYSTEMIC e
LOW sem voto humano voltam ao roteamento automático (CORROBORATING → avaliação), que decide:
sistêmico aprova; LOW aprova com régua reduzida ou aguarda evidência. MEDIUM/HIGH ficam na
Inbox. Nunca mexe em atom que já recebeu voto.
"""

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.kernel import events
from app.kernel.ir.envelope import LifecycleStatus, Significance
from app.llm import provider as llm
from app.models.knowledge import KnowledgeAtom
from app.models.review import Vote
from app.services import evaluation
from app.services import knowledge as ksvc
from app.services.embeddings import BUSINESS_KINDS

log = logging.getLogger(__name__)

ACTOR = "system:triage"
BATCH = 20

TRIAGE_SYSTEM = """\
Você classifica conhecimento extraído do código de um sistema legado pela RÉGUA DE RELEVÂNCIA.
Para cada item (id, título, afirmação) escolha UMA categoria:

- HIGH: muda dinheiro, imposto, estoque, comissão, status de documento ou uma decisão do
  negócio; políticas, exceções e regras legais/fiscais.
- MEDIUM: regra operacional de processo, cálculo auxiliar, condição que altera o fluxo.
- LOW: detalhe operacional com algum significado de negócio (valor padrão de parâmetro
  comercial, arredondamento de exibição, ordem de exibição com sentido comercial).
- SYSTEMIC: comportamento OBJETIVO, verificável só pelo código, sem decisão de negócio embutida:
  validação genérica de entrada (campo obrigatório, formato/máscara, data inicial maior que a
  final, número positivo, tamanho de texto, dígito verificador), comportamento de interface
  (habilitar/desabilitar, foco, paginação, ordenação, confirmação), infraestrutura (log,
  conexão, transação, cache, retry, permissão genérica de tela, tratamento técnico de erro,
  layout/estrutura de arquivo ou catálogo de códigos de um protocolo).

Teste mental: um gestor da área discutiria isto numa reunião de negócio (HIGH/MEDIUM/LOW) ou
delegaria ao time técnico sem discutir (SYSTEMIC)?

Responda SOMENTE com JSON válido, sem comentários, no formato:
{"items": [{"id": "<id recebido>", "significance": "HIGH|MEDIUM|LOW|SYSTEMIC",
            "reason": "<1 frase>"}]}
Inclua TODOS os ids recebidos, exatamente como vieram."""


def _parse(texto: str) -> dict[str, dict]:
    t = texto.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    saida: dict[str, dict] = {}
    for item in data.get("items", []) if isinstance(data, dict) else []:
        sid = str(item.get("id", "")).strip()
        sig = str(item.get("significance", "")).strip().upper()
        if sig == "TRIVIAL":
            sig = str(Significance.SYSTEMIC)
        if sid and sig in Significance.__members__:
            saida[sid] = {"significance": sig, "reason": str(item.get("reason", ""))[:300]}
    return saida


def classify_significance(
    items: list[dict], provider: llm.LLMProvider | None = None
) -> dict[str, dict]:
    """items: [{id, title, statement}] → {id: {significance, reason}} (ids não devolvidos
    pelo modelo ficam de fora — o chamador decide o que fazer com eles)."""
    provider = provider or llm.get_provider()
    saida: dict[str, dict] = {}
    for i in range(0, len(items), BATCH):
        lote = items[i : i + BATCH]
        user = json.dumps({"items": lote}, ensure_ascii=False)
        try:
            resposta = provider.complete(system=TRIAGE_SYSTEM, user=user, max_tokens=4000)
        except Exception:
            log.warning("triagem: lote %d falhou no provider", i // BATCH, exc_info=True)
            continue
        saida.update(_parse(resposta))
    return saida


def pending_atoms(
    db: Session, *, domain: str | None = None, limit: int = 200
) -> list[KnowledgeAtom]:
    """Em revisão humana, de negócio, SEM voto e SEM relevância marcada."""
    votados = select(Vote.atom_id)
    stmt = (
        select(KnowledgeAtom)
        .where(
            KnowledgeAtom.status == str(LifecycleStatus.NEEDS_HUMAN_REVIEW),
            KnowledgeAtom.kind.in_(BUSINESS_KINDS),
            KnowledgeAtom.significance.is_(None),
            KnowledgeAtom.id.not_in(votados),
        )
        .order_by(KnowledgeAtom.created_at)
        .limit(limit)
    )
    if domain:
        stmt = stmt.where(KnowledgeAtom.domain == domain)
    return list(db.scalars(stmt))


def triage_pending(
    db: Session,
    *,
    domain: str | None = None,
    limit: int = 200,
    apply: bool = True,
    provider: llm.LLMProvider | None = None,
    actor: str = ACTOR,
) -> dict:
    atoms = pending_atoms(db, domain=domain, limit=limit)
    resumo = {
        "considered": len(atoms),
        "classified": 0,
        "unclassified": 0,
        "by_significance": {s: 0 for s in Significance.__members__},
        "rerouted": 0,
        "auto_approved": 0,
        "awaiting_evidence": 0,
        "still_human": 0,
        "dry_run": not apply,
    }
    if not atoms:
        return resumo
    itens = [
        {
            "id": a.id,
            "title": a.title,
            "statement": ((a.body or {}).get("statement") or a.description or "")[:600],
        }
        for a in atoms
    ]
    classes = classify_significance(itens, provider)
    modelo = getattr(provider or llm.get_provider(), "model", "unknown")

    for atom in atoms:
        cls = classes.get(atom.id)
        if cls is None:
            resumo["unclassified"] += 1
            continue
        sig = cls["significance"]
        resumo["classified"] += 1
        resumo["by_significance"][sig] += 1
        if not apply:
            continue
        atom.significance = sig
        events.record_event(
            db, events.SIGNIFICANCE_ASSIGNED, actor, atom.id,
            {"significance": sig, "reason": cls["reason"], "model": modelo, "source": "triage"},
        )
        if sig in (str(Significance.SYSTEMIC), str(Significance.LOW)):
            # volta ao ciclo automático (transição permitida: sem voto humano)
            ksvc.change_status(
                db, atom.id, actor=actor,
                new_status=LifecycleStatus.CORROBORATING,
                reason=f"triagem de relevância: {sig.lower()} não exige revisão humana",
                expected_lock_version=atom.lock_version,
            )
            res = evaluation.evaluate_atom(db, atom.id, actor=actor, trigger="triage")
            resumo["rerouted"] += 1
            status = res.get("status")
            if status == str(LifecycleStatus.CANONICAL):
                resumo["auto_approved"] += 1
            elif status == str(LifecycleStatus.CORROBORATING):
                resumo["awaiting_evidence"] += 1
            else:
                resumo["still_human"] += 1
        else:
            resumo["still_human"] += 1
    db.commit()
    return resumo
