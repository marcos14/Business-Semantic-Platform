"""Semantic Governance Workspace (PRD §36-§44): votos, comentários, decisão, inbox, kanban.

Votação NUNCA é aprovação automática (§42): a canonicalização continua passando
pelos gates do kernel. Votos assertivos viram evidence humana (§24), alimentando
o Confidence Engine.
"""

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.kernel import events, governance
from app.kernel.errors import KernelError
from app.kernel.governance import DecisionAction, ReviewAction
from app.kernel.ir.envelope import (
    AtomKind,
    Classification,
    EvidenceRelation,
    EvidenceType,
    LifecycleStatus,
    Origin,
)
from app.kernel.policy import DEFAULT_THRESHOLD
from app.models.auth import Role, User
from app.models.knowledge import AtomRelation, Evidence, EvidenceLink, KnowledgeAtom
from app.models.review import Comment, Vote
from app.rbac.roles import ROLE_IMPLIES, has_role
from app.services import evaluation, notify
from app.services import knowledge as ksvc

REVIEWABLE = {str(s) for s in governance.REVIEWABLE_STATUSES}


def _role_at_vote(user: User, atom: KnowledgeAtom) -> tuple[str, bool]:
    is_expert = has_role(user, Role.DOMAIN_EXPERT, atom.domain, atom.capability)
    for role in (Role.ADMINISTRATOR, Role.DECISION_OWNER, Role.DOMAIN_EXPERT, Role.REVIEWER):
        if has_role(user, role, atom.domain, atom.capability):
            return role.value, is_expert
    return Role.REVIEWER.value, is_expert


def _walk_to(db: Session, atom: KnowledgeAtom, target: LifecycleStatus, actor: str, reason: str,
             authority: bool = False) -> KnowledgeAtom:
    """Percorre transições intermediárias óbvias até target (cada passo auditado)."""
    caminho = {
        LifecycleStatus.NEEDS_HUMAN_REVIEW: [LifecycleStatus.IN_REVIEW],
        LifecycleStatus.IN_REVIEW: [],
        LifecycleStatus.DECISION_PENDING: [],
    }.get(LifecycleStatus(atom.status), [])
    for intermediario in caminho:
        if intermediario == target:
            break
        atom = ksvc.change_status(
            db, atom.id, actor=actor, new_status=intermediario, reason=reason,
            expected_lock_version=atom.lock_version,
        )
    if LifecycleStatus(atom.status) == target:
        return atom
    if target in (LifecycleStatus.CANONICAL,) and LifecycleStatus(atom.status) not in (
        LifecycleStatus.DECISION_PENDING,
        LifecycleStatus.AUTO_APPROVED,
    ):
        atom = ksvc.change_status(
            db, atom.id, actor=actor, new_status=LifecycleStatus.DECISION_PENDING,
            reason=reason, expected_lock_version=atom.lock_version,
        )
    return ksvc.change_status(
        db, atom.id, actor=actor, new_status=target, reason=reason,
        expected_lock_version=atom.lock_version, authority_granted=authority,
    )


def start_review(db: Session, atom_id: str, user: User) -> KnowledgeAtom:
    atom = ksvc.get_atom(db, atom_id)
    return ksvc.change_status(
        db, atom_id, actor=user.email, new_status=LifecycleStatus.IN_REVIEW,
        reason="revisão iniciada", expected_lock_version=atom.lock_version,
    )


def submit_vote(
    db: Session, atom_id: str, user: User, action: ReviewAction, comment: str | None
) -> Vote:
    atom = ksvc.get_atom(db, atom_id)
    if atom.status not in REVIEWABLE:
        raise KernelError(f"Atom em {atom.status} não está em revisão")
    # Primeiro voto abre a discussão (§38: Needs Review → In Discussion)
    if atom.status == str(LifecycleStatus.NEEDS_HUMAN_REVIEW):
        atom = ksvc.change_status(
            db, atom_id, actor=user.email, new_status=LifecycleStatus.IN_REVIEW,
            reason="primeiro voto abriu a discussão", expected_lock_version=atom.lock_version,
        )

    role, is_expert = _role_at_vote(user, atom)
    vote = db.scalar(
        select(Vote).where(Vote.atom_id == atom_id, Vote.reviewer_id == user.id)
    )
    if vote is None:
        vote = Vote(atom_id=atom_id, reviewer_id=user.id)
        db.add(vote)
    vote.action = str(action)
    vote.comment = comment
    vote.role_at_vote = role
    vote.is_domain_expert = is_expert
    db.flush()

    events.record_event(
        db, events.VOTE_SUBMITTED, user.email, atom_id,
        {"action": str(action), "role": role, "domain_expert": is_expert, "comment": comment},
    )

    # §24: voto assertivo vira evidence humana (uma por reviewer; mudanças só no audit)
    if action in governance.ASSERTIVE_ACTIONS:
        ja_tem = db.scalar(
            select(Evidence)
            .join(EvidenceLink, EvidenceLink.evidence_id == Evidence.id)
            .where(
                EvidenceLink.atom_id == atom_id,
                Evidence.meta["reviewer"].astext == user.email,
            )
        )
        if ja_tem is None:
            ksvc.add_evidence(
                db, atom_id, actor=user.email, origin=Origin.HUMAN,
                type=EvidenceType.DOMAIN_EXPERT if is_expert else EvidenceType.HUMAN_REVIEW,
                relation=EvidenceRelation.CONTRADICTS
                if action == ReviewAction.REJECT
                else EvidenceRelation.SUPPORTS,
                summary=f"Revisão humana: {action} por {role}",
                metadata={"reviewer": user.email, "role": role, "decision": str(action)},
            )
    return vote


def add_comment(db: Session, atom_id: str, user: User, text: str) -> Comment:
    atom = ksvc.get_atom(db, atom_id)
    c = Comment(atom_id=atom_id, author_id=user.id, text=text)
    db.add(c)
    notify.notify_mentions(db, atom, text, author_id=user.id)
    return c


def request_evidence(db: Session, atom_id: str, user: User, note: str) -> KnowledgeAtom:
    atom = ksvc.get_atom(db, atom_id)
    return ksvc.change_status(
        db, atom_id, actor=user.email, new_status=LifecycleStatus.CORROBORATING,
        reason=f"mais evidência solicitada: {note}", expected_lock_version=atom.lock_version,
    )


def ready_for_decision(db: Session, atom_id: str, user: User) -> KnowledgeAtom:
    atom = ksvc.get_atom(db, atom_id)
    atom = ksvc.change_status(
        db, atom_id, actor=user.email, new_status=LifecycleStatus.DECISION_PENDING,
        reason="pronto para decisão", expected_lock_version=atom.lock_version,
    )
    notify.notify_owners(
        db, atom, type="decision_needed",
        message=f"Decisão aguardando owner: {atom.title}", exclude_user_id=user.id,
    )
    return atom


def decide(
    db: Session,
    atom_id: str,
    owner: User,
    *,
    action: DecisionAction,
    reason: str,
    expected_lock_version: int,
    classification: Classification | None = None,
    exception: dict | None = None,
) -> KnowledgeAtom:
    """Decisão final (§43). O router garante autoridade de Decision Owner no escopo."""
    atom = ksvc.get_atom(db, atom_id)
    if atom.lock_version != expected_lock_version:
        # §105: dois owners decidindo ao mesmo tempo → o segundo recebe 409
        from app.kernel.errors import StaleVersionError

        raise StaleVersionError(
            f"Versão desatualizada: esperada {expected_lock_version}, atual {atom.lock_version}"
        )

    events.record_event(
        db, events.DECISION_MADE, owner.email, atom_id,
        {"decision_action": str(action), "reason": reason, "by_role": "decision_owner"},
    )

    if action == DecisionAction.APPROVE:
        # §24: a aprovação do owner também é evidence
        ksvc.add_evidence(
            db, atom_id, actor=owner.email, origin=Origin.HUMAN,
            type=EvidenceType.HUMAN_REVIEW,
            summary=f"Aprovação do Decision Owner: {reason}",
            metadata={"reviewer": owner.email, "role": "decision_owner", "decision": "APPROVE"},
        )
        atom = ksvc.get_atom(db, atom_id)
        return _walk_to(
            db, atom, LifecycleStatus.CANONICAL, owner.email, reason, authority=True
        )
    if action == DecisionAction.REJECT:
        return _walk_to(db, atom, LifecycleStatus.REJECTED, owner.email, reason)
    if action == DecisionAction.MARK_KNOWN_BUG:
        atom = ksvc.update_atom(
            db, atom_id, actor=owner.email, expected_lock_version=atom.lock_version,
            changes={"classification": Classification.KNOWN_BUG},
        )
        return _walk_to(db, atom, LifecycleStatus.LEGACY_BUG, owner.email, reason)
    if action == DecisionAction.RECLASSIFY:
        if classification is None:
            raise KernelError("RECLASSIFY exige classification")
        return ksvc.update_atom(
            db, atom_id, actor=owner.email, expected_lock_version=atom.lock_version,
            changes={"classification": classification},
        )
    if action == DecisionAction.REQUEST_EVIDENCE:
        return _walk_to(db, atom, LifecycleStatus.CORROBORATING, owner.email, reason)
    if action == DecisionAction.ADD_EXCEPTION:
        if not exception or not exception.get("title") or not exception.get("condition"):
            raise KernelError("ADD_EXCEPTION exige {title, condition}")
        ksvc.create_candidate(
            db, actor=owner.email, origin=Origin.HUMAN, kind=AtomKind.EXCEPTION,
            title=exception["title"], domain=atom.domain, capability=atom.capability,
            body={"applies_to": atom.id, "condition": exception["condition"]},
            evidence=[
                {
                    "type": EvidenceType.HUMAN_REVIEW,
                    "summary": f"Exceção definida pelo owner ao decidir {atom.id}",
                    "metadata": {"reviewer": owner.email, "decision": "ADD_EXCEPTION"},
                }
            ],
        )
        return atom
    raise KernelError(f"Ação de decisão desconhecida: {action}")


# ---------- Leituras: inbox, kanban, decision room ----------


def _reviewer_domains(user: User) -> list[str] | None:
    """None = todos os domains (binding global); [] = nenhum."""
    domains: set[str] = set()
    for b in user.bindings:
        if Role.REVIEWER in ROLE_IMPLIES[b.role]:
            if b.domain_slug is None:
                return None
            domains.add(b.domain_slug)
    return sorted(domains)


def _conflict_counts(db: Session, atom_ids: list[str]) -> dict[str, int]:
    if not atom_ids:
        return {}
    rows = db.execute(
        select(EvidenceLink.atom_id, func.count())
        .where(
            EvidenceLink.atom_id.in_(atom_ids),
            EvidenceLink.relation == str(EvidenceRelation.CONTRADICTS),
        )
        .group_by(EvidenceLink.atom_id)
    ).all()
    return dict(rows)


def _centralities(db: Session, atom_ids: list[str]) -> dict[str, int]:
    if not atom_ids:
        return {}
    contagem: dict[str, int] = {}
    rows = db.execute(
        select(AtomRelation.from_atom, AtomRelation.to_atom).where(
            or_(AtomRelation.from_atom.in_(atom_ids), AtomRelation.to_atom.in_(atom_ids))
        )
    ).all()
    for a, b in rows:
        contagem[a] = contagem.get(a, 0) + 1
        contagem[b] = contagem.get(b, 0) + 1
    return contagem


def _card(atom: KnowledgeAtom, conflicts: int, votes: int, supports: int) -> dict:
    """Review Card (§39): só o suficiente para triagem."""
    return {
        "id": atom.id,
        "kind": atom.kind,
        "title": atom.title,
        "domain": atom.domain,
        "capability": atom.capability,
        "status": atom.status,
        "confidence": atom.confidence,
        "risk": atom.risk,
        "supporting_evidence": supports,
        "conflicting_evidence": conflicts,
        "votes": votes,
        "lock_version": atom.lock_version,
    }


def _support_counts(db: Session, atom_ids: list[str]) -> dict[str, int]:
    if not atom_ids:
        return {}
    rows = db.execute(
        select(EvidenceLink.atom_id, func.count())
        .where(
            EvidenceLink.atom_id.in_(atom_ids),
            EvidenceLink.relation == str(EvidenceRelation.SUPPORTS),
        )
        .group_by(EvidenceLink.atom_id)
    ).all()
    return dict(rows)


def _vote_counts(db: Session, atom_ids: list[str]) -> dict[str, int]:
    if not atom_ids:
        return {}
    rows = db.execute(
        select(Vote.atom_id, func.count()).where(Vote.atom_id.in_(atom_ids)).group_by(Vote.atom_id)
    ).all()
    return dict(rows)


def _scoped_atoms(db: Session, user: User, statuses: set[str]) -> list[KnowledgeAtom]:
    domains = _reviewer_domains(user)
    if domains == []:
        return []
    stmt = select(KnowledgeAtom).where(KnowledgeAtom.status.in_(statuses))
    if domains is not None:
        stmt = stmt.where(KnowledgeAtom.domain.in_(domains))
    return list(db.scalars(stmt))


def inbox(db: Session, user: User) -> dict:
    """Inbox personalizada (§37) ordenada pela prioridade composta (§84)."""
    atoms = _scoped_atoms(db, user, REVIEWABLE)
    ids = [a.id for a in atoms]
    conflicts = _conflict_counts(db, ids)
    centrality = _centralities(db, ids)
    votes = _vote_counts(db, ids)
    supports = _support_counts(db, ids)
    agora = datetime.now(UTC)

    itens = []
    for a in atoms:
        prio = governance.review_priority(
            risk=a.risk,
            confidence=a.confidence,
            threshold=DEFAULT_THRESHOLD,
            conflict_count=conflicts.get(a.id, 0),
            age_days=(agora - a.created_at).total_seconds() / 86400,
            centrality=centrality.get(a.id, 0),
        )
        item = _card(a, conflicts.get(a.id, 0), votes.get(a.id, 0), supports.get(a.id, 0))
        item["priority"] = prio.as_dict()
        item["needs_your_decision"] = a.status == str(LifecycleStatus.DECISION_PENDING) and (
            has_role(user, Role.DECISION_OWNER, a.domain, a.capability)
        )
        itens.append(item)
    itens.sort(key=lambda i: -i["priority"]["score"])

    challenged = 0
    canonicos = _scoped_atoms(db, user, {str(LifecycleStatus.CANONICAL)})
    challenged = sum(
        1 for cid, n in _conflict_counts(db, [c.id for c in canonicos]).items() if n > 0
    )
    return {
        "summary": {
            "awaiting_review": sum(
                1
                for i in itens
                if i["status"]
                in (str(LifecycleStatus.NEEDS_HUMAN_REVIEW), str(LifecycleStatus.IN_REVIEW))
            ),
            "needs_decision": sum(1 for i in itens if i["needs_your_decision"]),
            "with_conflicts": sum(1 for i in itens if i["conflicting_evidence"] > 0),
            "canonical_challenged": challenged,
        },
        "items": itens,
    }


def kanban(db: Session, user: User, domain: str | None, capability: str | None) -> dict:
    todos_status = {str(s) for col in governance.KANBAN_COLUMNS.values() for s in col}
    atoms = _scoped_atoms(db, user, todos_status)
    if domain:
        atoms = [a for a in atoms if a.domain == domain]
    if capability:
        atoms = [a for a in atoms if a.capability == capability]
    ids = [a.id for a in atoms]
    conflicts = _conflict_counts(db, ids)
    votes = _vote_counts(db, ids)
    supports = _support_counts(db, ids)
    colunas: dict[str, list[dict]] = {c: [] for c in governance.KANBAN_COLUMNS}
    for a in atoms:
        for col, statuses in governance.KANBAN_COLUMNS.items():
            if a.status in {str(s) for s in statuses}:
                colunas[col].append(
                    _card(a, conflicts.get(a.id, 0), votes.get(a.id, 0), supports.get(a.id, 0))
                )
                break
    return {"columns": colunas}


def decision_room(db: Session, atom_id: str, user: User) -> dict:
    """Payload completo da Decision Room (§40) + resumo do owner (§44)."""
    atom = db.get(
        KnowledgeAtom, atom_id, options=[selectinload(KnowledgeAtom.evidence_links)]
    )
    if atom is None:
        from app.kernel.errors import NotFoundError

        raise NotFoundError(f"Atom não encontrado: {atom_id}")

    evidencias = []
    for link in atom.evidence_links:
        ev = link.evidence
        evidencias.append(
            {
                "id": str(ev.id),
                "type": ev.type,
                "relation": link.relation,
                "summary": ev.summary,
                "excerpt": ev.excerpt,
                "location": ev.location,
                "origin": ev.origin,
                "created_by": ev.created_by,
            }
        )

    votos = db.scalars(
        select(Vote).where(Vote.atom_id == atom_id).options(selectinload(Vote.reviewer))
    ).all()
    comments = db.scalars(
        select(Comment)
        .where(Comment.atom_id == atom_id)
        .order_by(Comment.created_at)
        .options(selectinload(Comment.author))
    ).all()
    relacoes = db.execute(
        select(AtomRelation, KnowledgeAtom.title)
        .join(KnowledgeAtom, KnowledgeAtom.id == AtomRelation.to_atom)
        .where(AtomRelation.from_atom == atom_id)
    ).all()
    relacoes_in = db.execute(
        select(AtomRelation, KnowledgeAtom.title)
        .join(KnowledgeAtom, KnowledgeAtom.id == AtomRelation.from_atom)
        .where(AtomRelation.to_atom == atom_id)
    ).all()

    conflito = any(e["relation"] == str(EvidenceRelation.CONTRADICTS) for e in evidencias)
    por_acao: dict[str, int] = {}
    experts: dict[str, int] = {}
    for v in votos:
        por_acao[v.action] = por_acao.get(v.action, 0) + 1
        if v.is_domain_expert:
            experts[v.action] = experts.get(v.action, 0) + 1

    meu_voto = next((v for v in votos if v.reviewer_id == user.id), None)
    pode_decidir = has_role(user, Role.DECISION_OWNER, atom.domain, atom.capability)

    return {
        "atom": {
            "id": atom.id,
            "kind": atom.kind,
            "title": atom.title,
            "description": atom.description,
            "statement": (atom.body or {}).get("statement"),
            "domain": atom.domain,
            "capability": atom.capability,
            "status": atom.status,
            "classification": atom.classification,
            "confidence": atom.confidence,
            "risk": atom.risk,
            "scope": atom.scope,
            "body": atom.body,
            "origin": atom.origin,
            "version": atom.version,
            "lock_version": atom.lock_version,
        },
        "confidence": evaluation.latest_confidence(db, atom_id),
        "evidence": [e for e in evidencias if e["relation"] == "supports"],
        "contradicting_evidence": [e for e in evidencias if e["relation"] == "contradicts"],
        "relations": [
            {"direction": "out", "type": r.type, "atom": r.to_atom, "title": t}
            for r, t in relacoes
        ]
        + [
            {"direction": "in", "type": r.type, "atom": r.from_atom, "title": t}
            for r, t in relacoes_in
        ],
        "votes": [
            {
                "reviewer": v.reviewer.name,
                "email": v.reviewer.email,
                "role": v.role_at_vote,
                "domain_expert": v.is_domain_expert,
                "action": v.action,
                "comment": v.comment,
                "at": v.updated_at.isoformat(),
            }
            for v in votos
        ],
        "comments": [
            {
                "author": c.author.name,
                "email": c.author.email,
                "text": c.text,
                "at": c.created_at.isoformat(),
            }
            for c in comments
        ],
        "summary": {
            "total_votes": len(votos),
            "by_action": por_acao,
            "domain_experts": experts,
            "recommendation": governance.recommend(
                confidence=atom.confidence, has_conflict=conflito
            ),
        },
        "my_vote": meu_voto.action if meu_voto else None,
        "permissions": {
            "can_vote": has_role(user, Role.REVIEWER, atom.domain, atom.capability)
            and atom.status in REVIEWABLE,
            "can_decide": pode_decidir,
        },
    }
