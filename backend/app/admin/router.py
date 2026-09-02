import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.db import get_db
from app.models.auth import Capability, Domain, Role, RoleBinding, User
from app.rbac.deps import require

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


# ---------- Domains / Capabilities ----------


class DomainIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=100)
    name: str = Field(min_length=1, max_length=200)


@router.post("/domains", status_code=status.HTTP_201_CREATED)
def create_domain(body: DomainIn, db: Session = Depends(get_db)) -> dict:
    if db.get(Domain, body.slug):
        raise HTTPException(status.HTTP_409_CONFLICT, "Domain já existe")
    db.add(Domain(slug=body.slug, name=body.name))
    db.commit()
    return {"slug": body.slug, "name": body.name}


@router.get("/domains")
def list_domains(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"slug": d.slug, "name": d.name}
        for d in db.scalars(select(Domain).order_by(Domain.slug))
    ]


class CapabilityIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=100)
    domain_slug: str
    name: str = Field(min_length=1, max_length=200)


@router.post("/capabilities", status_code=status.HTTP_201_CREATED)
def create_capability(body: CapabilityIn, db: Session = Depends(get_db)) -> dict:
    if db.get(Domain, body.domain_slug) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Domain inexistente")
    if db.get(Capability, body.slug):
        raise HTTPException(status.HTTP_409_CONFLICT, "Capability já existe")
    db.add(Capability(slug=body.slug, domain_slug=body.domain_slug, name=body.name))
    db.commit()
    return {"slug": body.slug, "domain_slug": body.domain_slug, "name": body.name}


@router.get("/capabilities")
def list_capabilities(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"slug": c.slug, "domain_slug": c.domain_slug, "name": c.name}
        for c in db.scalars(select(Capability).order_by(Capability.slug))
    ]


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


@router.delete("/role-bindings/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_binding(binding_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    binding = db.get(RoleBinding, binding_id)
    if binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Binding inexistente")
    db.delete(binding)
    db.commit()
