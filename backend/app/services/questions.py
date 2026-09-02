"""Question Management (PRD §51): responder, atribuir, converter resposta em rule."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.kernel.errors import KernelError, NotFoundError
from app.kernel.ir.envelope import AtomKind, EvidenceType, Origin, RelationType
from app.models.auth import User
from app.models.knowledge import KnowledgeAtom
from app.services import knowledge as ksvc
from app.services import notify


def get_question(db: Session, question_id: str) -> KnowledgeAtom:
    atom = ksvc.get_atom(db, question_id)
    if atom.kind != str(AtomKind.QUESTION):
        raise KernelError(f"{question_id} não é uma question")
    return atom


def answer(db: Session, question_id: str, user: User, *, answer_text: str) -> KnowledgeAtom:
    q = get_question(db, question_id)
    return ksvc.update_atom(
        db, question_id, actor=user.email,
        expected_lock_version=q.lock_version,
        changes={"body": {**q.body, "answer": answer_text}},
    )


def assign(db: Session, question_id: str, user: User, *, assignee_email: str) -> KnowledgeAtom:
    from app.models.auth import User as UserModel

    q = get_question(db, question_id)
    destinatario = db.scalar(select(UserModel).where(UserModel.email == assignee_email.lower()))
    if destinatario is None:
        raise NotFoundError(f"Usuário inexistente: {assignee_email}")
    q = ksvc.update_atom(
        db, question_id, actor=user.email,
        expected_lock_version=q.lock_version,
        changes={"body": {**q.body, "assigned_to": destinatario.email}},
    )
    # §73: "Question assigned"
    notify.notify(
        db, {destinatario.id},
        type="question_assigned",
        message=f"Question atribuída a você: {q.title}",
        atom_id=q.id,
    )
    return q


def convert_to_rule(
    db: Session,
    question_id: str,
    user: User,
    *,
    title: str,
    statement: str,
    scope: dict | None = None,
) -> KnowledgeAtom:
    """§51: converter resposta em rule — a resposta do especialista é a evidência (§24)."""
    q = get_question(db, question_id)
    if (q.body or {}).get("converted_to"):
        raise KernelError(f"Question já convertida em {q.body['converted_to']}")
    if not (q.body or {}).get("answer"):
        raise KernelError("Question sem resposta registrada não pode virar rule")
    rule = ksvc.create_candidate(
        db, actor=user.email, origin=Origin.HUMAN, kind=AtomKind.RULE,
        title=title, domain=q.domain, capability=q.capability, scope=scope,
        body={"statement": statement},
        evidence=[{
            "type": EvidenceType.DOMAIN_EXPERT,
            "summary": f"Resposta da question {q.id}: {q.body['answer'][:300]}",
            "metadata": {"reviewer": user.email, "decision": "CONVERT_QUESTION", "question": q.id},
        }],
    )
    db.flush()
    ksvc.add_relation(
        db, actor=user.email, from_atom=q.id, to_atom=rule.id,
        relation_type=RelationType.PRODUCES,
    )
    q = ksvc.get_atom(db, question_id)
    ksvc.update_atom(
        db, question_id, actor=user.email,
        expected_lock_version=q.lock_version,
        changes={"body": {**q.body, "converted_to": rule.id}},
    )
    return rule
