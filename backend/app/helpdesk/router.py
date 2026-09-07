import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_optional_user
from app.config import settings
from app.db import get_db
from app.helpdesk.contracts import (
    Answerability,
    ConsumerProfile,
    FeedbackOutcome,
    RecommendedAction,
)
from app.kernel.ir.envelope import LifecycleStatus
from app.models.auth import Role, User
from app.models.helpdesk import (
    HelpDeskClientCredential,
    HelpDeskInteraction,
    HelpDeskPolicy,
)
from app.models.knowledge import Source
from app.rbac.deps import ensure_scope_role
from app.rbac.roles import has_role
from app.services import helpdesk as svc

router = APIRouter(prefix="/helpdesk", tags=["helpdesk"])
_api_key = APIKeyHeader(name="X-BSP-API-Key", auto_error=False)


def _credential_hash(secret: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), secret.encode(), hashlib.sha256).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def get_helpdesk_user(
    request: Request,
    bearer_user: User | None = Depends(get_optional_user),
    api_key: str | None = Depends(_api_key),
    db: Session = Depends(get_db),
) -> User:
    """Aceita usuário JWT ou uma identidade de máquina rotacionável e escopada."""
    if bearer_user is not None:
        request.state.helpdesk_consumer = bearer_user.email
        request.state.helpdesk_allowed_profiles = None
        return bearer_user
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Credencial inválida")
    if not api_key or "." not in api_key:
        raise unauthorized
    client_id, secret = api_key.split(".", 1)
    credential = db.scalar(
        select(HelpDeskClientCredential)
        .where(HelpDeskClientCredential.client_id == client_id)
        .with_for_update()
    )
    if (
        credential is None
        or not credential.active
        or not hmac.compare_digest(credential.secret_hash, _credential_hash(secret))
    ):
        raise unauthorized
    now = datetime.now(UTC)
    if credential.expires_at and _aware(credential.expires_at) <= now:
        raise unauthorized
    window = _aware(credential.rate_window_started_at)
    if (now - window).total_seconds() >= 60:
        credential.rate_window_started_at = now
        credential.request_count = 0
    if credential.request_count >= credential.rate_limit_per_minute:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit excedido")
    credential.request_count += 1
    credential.last_used_at = now
    user = db.get(User, credential.user_id)
    if user is None or not user.active:
        raise unauthorized
    # Persiste rotação da janela mesmo quando o endpoint consultado é somente leitura.
    db.commit()
    request.state.helpdesk_consumer = f"client:{credential.client_id}"
    request.state.helpdesk_allowed_profiles = set(credential.allowed_profiles or [])
    return user


class ConversationIn(BaseModel):
    previous_question_ids: list[str] = Field(default_factory=list, max_length=50)
    facts_already_collected: list[str] = Field(default_factory=list, max_length=100)


class ContextRequest(BaseModel):
    question: str = Field(min_length=2, max_length=8000)
    consumer_profile: ConsumerProfile = ConsumerProfile.DIRECT
    domain: str | None = None
    capability: str | None = None
    context: dict = Field(default_factory=dict)
    conversation: ConversationIn | None = None
    persist_interaction: bool = True


class ContextBudgetOut(BaseModel):
    maximum_tokens: int
    estimated_tokens: int
    items_considered: int
    items_included: int
    truncated: bool


class ContextAuditOut(BaseModel):
    retrieval_version: str
    excluded_count: int
    exclusion_reasons: dict[str, int]
    latency_ms: int | None = None


class ContextPackageOut(BaseModel):
    package_version: str
    generated_at: datetime
    knowledge_snapshot: dict
    request: dict
    untrusted_user_content: dict
    resolved_context: dict
    policy: dict
    answerability: Answerability
    recommended_action: RecommendedAction
    reason: str
    response_instructions: list[str]
    knowledge: list[dict]
    procedures: list[dict]
    known_conflicts: list[dict]
    open_questions: list[dict]
    clarifying_questions: list[str]
    escalation: dict | None
    citations: list[dict]
    budget: ContextBudgetOut
    audit: ContextAuditOut
    interaction_id: uuid.UUID | None = None


class FeedbackIn(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    outcome: FeedbackOutcome
    helpful_atom_ids: list[str] = Field(default_factory=list, max_length=200)
    misleading_atom_ids: list[str] = Field(default_factory=list, max_length=200)
    missing_information: str | None = Field(default=None, max_length=8000)
    correction: str | None = Field(default=None, max_length=8000)
    ticket_reference: str | None = Field(default=None, max_length=300)


class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    consumer_profile: ConsumerProfile
    scope_type: str = Field(
        pattern="^(global|consumer_profile|domain|capability|classification|significance|risk)$"
    )
    selector: str | None = Field(default=None, max_length=200)
    allowed_statuses: list[LifecycleStatus] = Field(min_length=1)
    minimum_confidence: dict[str, float] = Field(default_factory=dict)
    allow_stale: bool = False
    allow_conflicted: bool = False
    critical_requires_escalation: bool = True
    include_evidence_excerpt: bool = False
    include_internal_location: bool = False
    max_context_tokens: int = Field(default=8000, ge=1000, le=50000)
    active: bool = True
    detail: dict | None = None


class PolicyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    allowed_statuses: list[LifecycleStatus] | None = None
    minimum_confidence: dict[str, float] | None = None
    allow_stale: bool | None = None
    allow_conflicted: bool | None = None
    critical_requires_escalation: bool | None = None
    include_evidence_excerpt: bool | None = None
    include_internal_location: bool | None = None
    max_context_tokens: int | None = Field(default=None, ge=1000, le=50000)
    active: bool | None = None
    detail: dict | None = None


class EvaluationCase(BaseModel):
    id: str | None = None
    question: str = Field(min_length=2)
    domain: str | None = None
    capability: str | None = None
    context: dict = Field(default_factory=dict)
    error_messages: list[str] = Field(default_factory=list)
    expected_atom_ids: list[str] = Field(default_factory=list)


class EvaluationIn(BaseModel):
    consumer_profile: ConsumerProfile = ConsumerProfile.COPILOT_N1
    cases: list[EvaluationCase] = Field(min_length=1, max_length=1000)


class ClientCredentialIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    user_id: uuid.UUID
    allowed_profiles: list[ConsumerProfile] = Field(min_length=1)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000)
    expires_at: datetime | None = None


def _require_admin(user: User) -> None:
    if not has_role(user, Role.ADMINISTRATOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requer papel administrator global")


def _validate_policy(body: PolicyIn) -> None:
    if body.scope_type in ("domain", "capability", "risk") and not body.selector:
        raise HTTPException(422, "selector é obrigatório para este scope_type")
    for value in body.minimum_confidence.values():
        if not 0 <= value <= 1:
            raise HTTPException(422, "minimum_confidence deve estar entre 0 e 1")


@router.post("/context", response_model=ContextPackageOut)
def context_package(
    body: ContextRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_helpdesk_user),
) -> dict:
    allowed_profiles = request.state.helpdesk_allowed_profiles
    if allowed_profiles is not None and str(body.consumer_profile) not in allowed_profiles:
        raise HTTPException(403, "Consumer profile não autorizado para esta aplicação")
    package = svc.build_context(
        db,
        user=user,
        question=body.question,
        consumer_profile=body.consumer_profile,
        domain=body.domain,
        capability=body.capability,
        request_context=body.context,
        conversation=body.conversation.model_dump() if body.conversation else None,
        error_messages=list(body.context.get("error_messages") or []),
        persist_interaction=body.persist_interaction,
        consumer=request.state.helpdesk_consumer,
    )
    db.commit()
    return package


@router.get("/interactions/{interaction_id}")
def get_interaction(
    interaction_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_helpdesk_user),
) -> dict:
    row = db.get(HelpDeskInteraction, interaction_id)
    if row is None:
        raise HTTPException(404, "Interação inexistente")
    if row.consumer not in {user.email, request.state.helpdesk_consumer} and not has_role(
        user, Role.ADMINISTRATOR
    ):
        raise HTTPException(403, "Sem acesso à interação")
    return svc.interaction_out(row)


@router.post("/interactions/{interaction_id}/feedback", status_code=status.HTTP_201_CREATED)
def add_feedback(
    interaction_id: uuid.UUID,
    body: FeedbackIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_helpdesk_user),
) -> dict:
    row, candidate_id = svc.add_feedback(
        db,
        interaction_id=interaction_id,
        user=user,
        idempotency_key=body.idempotency_key,
        outcome=body.outcome,
        helpful_atom_ids=body.helpful_atom_ids,
        misleading_atom_ids=body.misleading_atom_ids,
        missing_information=body.missing_information,
        correction=body.correction,
        ticket_reference=body.ticket_reference,
        consumer=request.state.helpdesk_consumer,
    )
    db.commit()
    return svc.feedback_out(row, candidate_id)


@router.get("/policies")
def policies(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    _require_admin(user)
    return svc.list_policies(db)


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_policy(
    body: PolicyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    _validate_policy(body)
    row = HelpDeskPolicy(
        **body.model_dump(mode="json", exclude={"consumer_profile"}),
        consumer_profile=str(body.consumer_profile),
        created_by=user.email,
    )
    db.add(row)
    db.commit()
    return svc.resolve_policy(
        db,
        row.consumer_profile,
        domain=row.selector if row.scope_type == "domain" else None,
        capability=row.selector if row.scope_type == "capability" else None,
        risk=row.selector if row.scope_type == "risk" else None,
        classification=row.selector if row.scope_type == "classification" else None,
        significance=row.selector if row.scope_type == "significance" else None,
    )


@router.patch("/policies/{policy_id}")
def update_policy(
    policy_id: uuid.UUID,
    body: PolicyPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    row = db.get(HelpDeskPolicy, policy_id)
    if row is None:
        raise HTTPException(404, "Política inexistente")
    changes = body.model_dump(exclude_none=True)
    if "minimum_confidence" in changes and any(
        not 0 <= value <= 1 for value in changes["minimum_confidence"].values()
    ):
        raise HTTPException(422, "minimum_confidence deve estar entre 0 e 1")
    for key, value in changes.items():
        setattr(row, key, value)
    db.commit()
    return svc._policy_dict(row)


@router.get("/metrics")
def helpdesk_metrics(
    domain: str | None = None,
    capability: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if domain:
        ensure_scope_role(user, Role.VIEWER, domain, capability)
    return svc.metrics(db, user=user, domain=domain, capability=capability)


@router.get("/gaps")
def helpdesk_gaps(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    return svc.gaps(db, user=user, limit=limit)


@router.get("/freshness")
def freshness_report(
    domain: str | None = None,
    capability: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if domain:
        ensure_scope_role(user, Role.VIEWER, domain, capability)
    return svc.freshness_report(
        db,
        user=user,
        domain=domain,
        capability=capability,
        limit=limit,
    )


@router.post("/evaluate")
def evaluate(
    body: EvaluationIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return svc.evaluate_retrieval(
        db,
        user=user,
        cases=[case.model_dump() for case in body.cases],
        profile=body.consumer_profile,
    )


@router.post("/freshness/sources/{source_id}/refresh")
def refresh_freshness(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Source inexistente")
    if not source.repository or not Path(source.repository).is_dir():
        from app.jobs import defer_freshness

        queued = defer_freshness(str(source_id), delay_minutes=0)
        return {"source_id": str(source_id), "queued": queued, "execution": "discovery-host"}
    result = svc.refresh_source_freshness(db, source=source)
    db.commit()
    return result


def _credential_out(row: HelpDeskClientCredential) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "client_id": row.client_id,
        "user_id": str(row.user_id),
        "allowed_profiles": row.allowed_profiles,
        "rate_limit_per_minute": row.rate_limit_per_minute,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "active": row.active,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/clients")
def list_clients(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    _require_admin(user)
    return [
        _credential_out(row)
        for row in db.scalars(
            select(HelpDeskClientCredential).order_by(HelpDeskClientCredential.name)
        )
    ]


@router.post("/clients", status_code=status.HTTP_201_CREATED)
def create_client(
    body: ClientCredentialIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    target = db.get(User, body.user_id)
    if target is None or not target.active:
        raise HTTPException(422, "Usuário RBAC inexistente ou inativo")
    secret = secrets.token_urlsafe(32)
    row = HelpDeskClientCredential(
        name=body.name,
        client_id=f"hdc_{secrets.token_urlsafe(12)}",
        secret_hash=_credential_hash(secret),
        user_id=body.user_id,
        allowed_profiles=[str(profile) for profile in body.allowed_profiles],
        rate_limit_per_minute=body.rate_limit_per_minute,
        expires_at=body.expires_at,
        created_by=user.email,
    )
    db.add(row)
    db.commit()
    return {**_credential_out(row), "api_key": f"{row.client_id}.{secret}"}


@router.post("/clients/{credential_id}/rotate")
def rotate_client(
    credential_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    row = db.get(HelpDeskClientCredential, credential_id)
    if row is None:
        raise HTTPException(404, "Aplicação inexistente")
    secret = secrets.token_urlsafe(32)
    row.secret_hash = _credential_hash(secret)
    row.request_count = 0
    row.rate_window_started_at = datetime.now(UTC)
    row.active = True
    db.commit()
    return {**_credential_out(row), "api_key": f"{row.client_id}.{secret}"}


@router.delete("/clients/{credential_id}")
def revoke_client(
    credential_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    row = db.get(HelpDeskClientCredential, credential_id)
    if row is None:
        raise HTTPException(404, "Aplicação inexistente")
    row.active = False
    db.commit()
    return {"id": str(row.id), "active": False}
