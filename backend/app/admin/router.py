import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.passwords import hash_password
from app.db import get_db
from app.kernel.confidence import PROFILES
from app.kernel.ir.envelope import RiskLevel, Significance
from app.kernel.ir.registry import known_kinds
from app.kernel.policy import SCOPE_TYPES
from app.models.auth import Capability, Domain, Role, RoleBinding, User
from app.models.confidence import Policy
from app.rbac.deps import require
from app.services.profiles import profile_as_dict, profile_names

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require(Role.ADMINISTRATOR))],
)


# ---------- Users ----------


class UserIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    active: bool

    model_config = {"from_attributes": True}


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserIn, db: Session = Depends(get_db)) -> User:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado")
    user = User(email=email, name=body.name, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.email)))


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
) -> User:
    """Nome, situação (ativo/inativo) e senha. Desativar não apaga nada: bloqueia o login."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário inexistente")
    if body.name is not None:
        user.name = body.name
    if body.active is not None:
        if user.id == admin.id and not body.active:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Você não pode desativar a si mesmo"
            )
        user.active = body.active
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    db.commit()
    return user


# ---------- Domains / Capabilities ----------


class DomainIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=100)
    name: str = Field(min_length=1, max_length=200)
    evidence_profile: str | None = None


class DomainPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    evidence_profile: str | None = None


def _validate_profile(name: str | None) -> None:
    if name is not None and name not in PROFILES:
        raise HTTPException(422, f"evidence_profile inválido (use {profile_names()})")


def _domain_out(d: Domain) -> dict:
    return {"slug": d.slug, "name": d.name, "evidence_profile": d.evidence_profile}


@router.post("/domains", status_code=status.HTTP_201_CREATED)
def create_domain(body: DomainIn, db: Session = Depends(get_db)) -> dict:
    if db.get(Domain, body.slug):
        raise HTTPException(status.HTTP_409_CONFLICT, "Domain já existe")
    _validate_profile(body.evidence_profile)
    d = Domain(slug=body.slug, name=body.name, evidence_profile=body.evidence_profile)
    db.add(d)
    db.commit()
    return _domain_out(d)


@router.get("/domains")
def list_domains(db: Session = Depends(get_db)) -> list[dict]:
    return [_domain_out(d) for d in db.scalars(select(Domain).order_by(Domain.slug))]


@router.patch("/domains/{slug}")
def update_domain(slug: str, body: DomainPatch, db: Session = Depends(get_db)) -> dict:
    """Nome e perfil de evidência (pesos do Confidence Engine para este domain)."""
    d = db.get(Domain, slug)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain inexistente")
    if body.name is not None:
        d.name = body.name
    if "evidence_profile" in body.model_fields_set:
        _validate_profile(body.evidence_profile)
        d.evidence_profile = body.evidence_profile or None
    db.commit()
    return _domain_out(d)


@router.get("/evidence-profiles")
def list_evidence_profiles() -> list[dict]:
    """Perfis de evidência disponíveis, com os pesos (para a tela de admin explicar)."""
    return [profile_as_dict(p) for p in PROFILES.values()]


class CapabilityIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=100)
    domain_slug: str
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class CapabilityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


def _cap_out(c: Capability) -> dict:
    return {
        "slug": c.slug,
        "domain_slug": c.domain_slug,
        "name": c.name,
        "description": c.description,
    }


@router.post("/capabilities", status_code=status.HTTP_201_CREATED)
def create_capability(body: CapabilityIn, db: Session = Depends(get_db)) -> dict:
    if db.get(Domain, body.domain_slug) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain inexistente")
    if db.get(Capability, body.slug):
        raise HTTPException(status.HTTP_409_CONFLICT, "Capability já existe")
    cap = Capability(
        slug=body.slug, domain_slug=body.domain_slug, name=body.name,
        description=(body.description or None),
    )
    db.add(cap)
    db.commit()
    return _cap_out(cap)


@router.patch("/capabilities/{slug}")
def update_capability(slug: str, body: CapabilityPatch, db: Session = Depends(get_db)) -> dict:
    """Nome e descrição (a descrição orienta inventário e discovery dirigido)."""
    cap = db.get(Capability, slug)
    if cap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Capability inexistente")
    if body.name is not None:
        cap.name = body.name
    if "description" in body.model_fields_set:
        cap.description = body.description or None
    db.commit()
    return _cap_out(cap)


@router.get("/capabilities")
def list_capabilities(db: Session = Depends(get_db)) -> list[dict]:
    return [_cap_out(c) for c in db.scalars(select(Capability).order_by(Capability.slug))]


# ---------- Role bindings ----------


class BindingIn(BaseModel):
    user_id: uuid.UUID
    role: Role
    domain_slug: str | None = None
    capability_slug: str | None = None


class BindingOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role: Role
    domain_slug: str | None
    capability_slug: str | None

    model_config = {"from_attributes": True}


@router.post("/role-bindings", response_model=BindingOut, status_code=status.HTTP_201_CREATED)
def create_binding(body: BindingIn, db: Session = Depends(get_db)) -> RoleBinding:
    if db.get(User, body.user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário inexistente")
    if body.domain_slug is not None and db.get(Domain, body.domain_slug) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain inexistente")
    if body.capability_slug is not None:
        cap = db.get(Capability, body.capability_slug)
        if cap is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Capability inexistente")
        if body.domain_slug is None or cap.domain_slug != body.domain_slug:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Capability não pertence ao domain informado",
            )
    binding = RoleBinding(
        user_id=body.user_id,
        role=body.role,
        domain_slug=body.domain_slug,
        capability_slug=body.capability_slug,
    )
    db.add(binding)
    db.commit()
    return binding


@router.get("/role-bindings", response_model=list[BindingOut])
def list_bindings(
    user_id: uuid.UUID | None = None, db: Session = Depends(get_db)
) -> list[RoleBinding]:
    stmt = select(RoleBinding).order_by(RoleBinding.user_id, RoleBinding.role)
    if user_id is not None:
        stmt = stmt.where(RoleBinding.user_id == user_id)
    return list(db.scalars(stmt))


@router.delete("/role-bindings/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_binding(binding_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    binding = db.get(RoleBinding, binding_id)
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Binding inexistente")
    db.delete(binding)
    db.commit()


# ---------- Policies (§32-§35) ----------


class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scope_type: str
    selector: str | None = None
    threshold: float | None = Field(default=None, ge=0, le=1)
    human_review_required: bool | None = None
    min_reviewers: int | None = Field(default=None, ge=1)
    require_owner_approval: bool | None = None
    provisional_floor: float | None = Field(default=None, ge=0, le=1)
    active: bool = True


def _validate_policy_scope(db: Session, body: PolicyIn) -> None:
    if body.scope_type not in SCOPE_TYPES:
        raise HTTPException(422, f"scope_type inválido (use {sorted(SCOPE_TYPES)})")
    if body.scope_type == "global":
        if body.selector is not None:
            raise HTTPException(422, "Política global não usa selector")
        return
    if not body.selector:
        raise HTTPException(422, f"scope_type {body.scope_type} exige selector")
    if body.scope_type == "domain" and db.get(Domain, body.selector) is None:
        raise HTTPException(404, "Domain inexistente")
    if body.scope_type == "capability" and db.get(Capability, body.selector) is None:
        raise HTTPException(404, "Capability inexistente")
    if body.scope_type == "atom_kind" and body.selector not in known_kinds():
        raise HTTPException(422, f"Kind desconhecido: {body.selector}")
    if body.scope_type == "risk" and body.selector not in list(RiskLevel):
        raise HTTPException(422, f"Risk inválido: {body.selector}")
    if body.scope_type == "significance" and body.selector not in list(Significance):
        raise HTTPException(422, f"Significance inválida: {body.selector}")


def _policy_out(p: Policy) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "scope_type": p.scope_type,
        "selector": p.selector,
        "threshold": p.threshold,
        "human_review_required": p.human_review_required,
        "min_reviewers": p.min_reviewers,
        "require_owner_approval": p.require_owner_approval,
        "provisional_floor": p.provisional_floor,
        "active": p.active,
    }


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def create_policy(
    body: PolicyIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
) -> dict:
    _validate_policy_scope(db, body)
    p = Policy(**body.model_dump(), created_by=admin.email)
    db.add(p)
    db.commit()
    return _policy_out(p)


@router.get("/policies")
def list_policies(db: Session = Depends(get_db)) -> list[dict]:
    return [_policy_out(p) for p in db.scalars(select(Policy).order_by(Policy.created_at))]


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(policy_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    p = db.get(Policy, policy_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Política inexistente")
    db.delete(p)
    db.commit()
