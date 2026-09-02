"""API de Question Management (PRD §51)."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.kernel.ir.envelope import AtomKind
from app.models.auth import Role, User
from app.models.knowledge import KnowledgeAtom
from app.rbac.deps import ensure_scope_role
from app.services import questions as qsvc

router = APIRouter(prefix="/questions", tags=["questions"])


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1)


class AssignIn(BaseModel):
    assignee_email: EmailStr


class ConvertIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    statement: str = Field(min_length=1)
    scope: dict | None = None


def _out(q: KnowledgeAtom) -> dict:
    body = q.body or {}
    return {
        "id": q.id,
        "title": q.title,
        "domain": q.domain,
        "capability": q.capability,
        "status": q.status,
        "question": body.get("question"),
        "answer": body.get("answer"),
        "assigned_to": body.get("assigned_to"),
        "converted_to": body.get("converted_to"),
        "description": q.description,
        "created_by": q.created_by,
        "created_at": q.created_at.isoformat(),
        "lock_version": q.lock_version,
    }


@router.get("")
def list_questions(
    domain: str | None = None,
    capability: str | None = None,
    answered: bool | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = select(KnowledgeAtom).where(KnowledgeAtom.kind == str(AtomKind.QUESTION))
    if domain:
        stmt = stmt.where(KnowledgeAtom.domain == domain)
    if capability:
        stmt = stmt.where(KnowledgeAtom.capability == capability)
    rows = db.scalars(stmt.order_by(KnowledgeAtom.created_at.desc())).all()
    itens = [_out(q) for q in rows]
    if answered is True:
        itens = [i for i in itens if i["answer"]]
    elif answered is False:
        itens = [i for i in itens if not i["answer"]]
    return itens


@router.post("/{question_id}/answer")
def answer(
    question_id: str,
    body: AnswerIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    q = qsvc.get_question(db, question_id)
    # §7.3: Domain Expert resolve questions (admin também, pela hierarquia)
    ensure_scope_role(user, Role.DOMAIN_EXPERT, q.domain, q.capability)
    q = qsvc.answer(db, question_id, user, answer_text=body.answer)
    db.commit()
    return _out(q)


@router.post("/{question_id}/assign")
def assign(
    question_id: str,
    body: AssignIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    q = qsvc.get_question(db, question_id)
    ensure_scope_role(user, Role.REVIEWER, q.domain, q.capability)
    q = qsvc.assign(db, question_id, user, assignee_email=body.assignee_email)
    db.commit()
    return _out(q)


@router.post("/{question_id}/convert-to-rule", status_code=status.HTTP_201_CREATED)
def convert(
    question_id: str,
    body: ConvertIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    q = qsvc.get_question(db, question_id)
    ensure_scope_role(user, Role.DOMAIN_EXPERT, q.domain, q.capability)
    rule = qsvc.convert_to_rule(
        db, question_id, user, title=body.title, statement=body.statement, scope=body.scope
    )
    db.commit()
    return {"rule_id": rule.id, "question_id": question_id}
