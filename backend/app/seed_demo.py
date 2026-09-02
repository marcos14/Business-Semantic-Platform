"""Seed sintético para desenvolvimento da governança (Fase 3).

Uso: python -m app.seed_demo
Idempotente: se os usuários demo já existirem, não recria.

Usuários demo (senha: demo1234!):
  ana@demo.bsp    — Reviewer (finance)
  beto@demo.bsp   — Domain Expert (finance)
  carla@demo.bsp  — Decision Owner (finance)
"""

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.kernel.governance import ReviewAction
from app.kernel.ir.envelope import AtomKind, Origin, RiskLevel, SourceType
from app.models.auth import Capability, Domain, Role, RoleBinding, User
from app.models.knowledge import Source
from app.services import evaluation
from app.services import review as rsvc
from app.services.knowledge import create_candidate

SENHA = "demo1234!"

CAPABILITIES = [
    ("invoice-cancellation", "Invoice Cancellation"),
    ("payment-allocation", "Payment Allocation"),
    ("credit-limit", "Credit Limit Validation"),
]


def _user(db, email, name, role, domain="finance"):
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=name, password_hash=hash_password(SENHA))
        db.add(u)
        db.flush()
        db.add(RoleBinding(user_id=u.id, role=role, domain_slug=domain))
    return u


def _rule(db, cap, title, statement, evidence, risk=None, actor="agent:code-discovery"):
    return create_candidate(
        db,
        actor=actor,
        origin=Origin.AGENT,
        kind=AtomKind.RULE,
        title=title,
        domain="finance",
        capability=cap,
        scope={"country": "BR"},
        risk=RiskLevel(risk) if risk else None,
        body={"statement": statement},
        evidence=evidence,
    )


def _ev(type, file, **extra):
    return {"type": type, "location": {"file": file}, **extra}


def seed() -> None:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == "ana@demo.bsp")):
            print("Usuários demo já existem — seed pulado.")
            return

        if db.get(Domain, "finance") is None:
            db.add(Domain(slug="finance", name="Finance"))
            db.flush()
        for slug, name in CAPABILITIES:
            if db.get(Capability, slug) is None:
                db.add(Capability(slug=slug, domain_slug="finance", name=name))
        db.flush()

        ana = _user(db, "ana@demo.bsp", "Ana Reviewer", Role.REVIEWER)
        beto = _user(db, "beto@demo.bsp", "Beto Expert", Role.DOMAIN_EXPERT)
        carla = _user(db, "carla@demo.bsp", "Carla Owner", Role.DECISION_OWNER)
        db.flush()

        src = Source(
            type=str(SourceType.SOURCE_CODE),
            name="praxis-autonomous",
            repository="C:/Projetos/praxis-autonomous",
            branch="auth",
            domain_slug="finance",
            created_by="seed",
        )
        db.add(src)
        db.flush()

        # 1. Forte → caminho automático §99 (vira CANONICAL)
        a1 = _rule(
            db,
            "invoice-cancellation",
            "Nota cancelada não recebe pagamento",
            "Pagamentos não podem ser aplicados a notas com status cancelado.",
            [
                _ev("SOURCE_CODE", "InvoiceService.java",
                    excerpt="if (invoice.isCancelled()) reject();"),
                _ev("TEST", "InvoiceServiceTest.java",
                    summary="Teste garante rejeição de pagamento em nota cancelada"),
                _ev("DOCUMENT", "docs/ar-manual.md",
                    summary="Manual, seção 3.2: nota cancelada não aceita pagamento"),
                _ev("RUNTIME", "prod-2026-08.log",
                    summary="Traços de produção mostram rejeição consistente"),
            ],
        )
        db.flush()
        evaluation.evaluate_atom(db, a1.id, trigger="seed")

        # 2. Fraca, risco alto → NEEDS_HUMAN_REVIEW
        a2 = _rule(
            db,
            "invoice-cancellation",
            "Cancelamento permitido até o faturamento",
            "Uma nota pode ser cancelada apenas antes do faturamento.",
            [_ev("SOURCE_CODE", "CancelService.java")],
            risk="HIGH",
        )
        db.flush()
        evaluation.evaluate_atom(db, a2.id, trigger="seed")

        # 3. Com evidência contraditória + risco crítico → conflito em revisão, votos divergentes
        a3 = _rule(
            db,
            "payment-allocation",
            "Pagamento parcial quita a parcela mais antiga primeiro",
            "Alocação de pagamento parcial prioriza a parcela mais antiga em aberto.",
            [
                _ev("SOURCE_CODE", "AllocationService.java"),
                _ev("TEST", "AllocationTest.java", relation="contradicts",
                    summary="Teste mostra alocação proporcional, não FIFO"),
            ],
            risk="CRITICAL",
        )
        db.flush()
        evaluation.evaluate_atom(db, a3.id, trigger="seed")
        rsvc.submit_vote(db, a3.id, ana, ReviewAction.CONFIRM, "Confere com o código que li.")
        rsvc.submit_vote(
            db, a3.id, beto, ReviewAction.NEEDS_MORE_EVIDENCE,
            "O teste contradiz; precisamos de traço de produção.",
        )
        rsvc.add_comment(db, a3.id, ana, "O teste pode estar desatualizado — alguém confirma?")

        # 4. Em revisão com votos convergentes, pronta para decisão da Carla
        a4 = _rule(
            db,
            "credit-limit",
            "Pedido acima do limite de crédito exige aprovação de gerente",
            "Pedidos que excedem o limite de crédito do cliente exigem aprovação manual.",
            [
                _ev("SOURCE_CODE", "CreditService.java"),
                _ev("DOCUMENT", "docs/credit-policy.md", summary="Política de crédito, item 4"),
            ],
            risk="MEDIUM",
        )
        db.flush()
        evaluation.evaluate_atom(db, a4.id, trigger="seed")
        rsvc.submit_vote(db, a4.id, ana, ReviewAction.CONFIRM, None)
        rsvc.submit_vote(db, a4.id, beto, ReviewAction.CONFIRM_WITH_EXCEPTION,
                         "Clientes governo não passam por limite (§ contrato).")
        rsvc.ready_for_decision(db, a4.id, beto)

        # 5. Variedade para o explorer/kanban: concept, invariant, decision, scenario
        create_candidate(
            db, actor=carla.email, origin=Origin.HUMAN, kind=AtomKind.CONCEPT,
            title="Invoice", domain="finance", capability="invoice-cancellation",
            description="Obrigação financeira emitida para um cliente.",
        )
        _rule(
            db, "payment-allocation",
            "Saldo da nota nunca fica negativo",
            "O saldo remanescente de uma nota nunca pode ficar negativo.",
            [_ev("SOURCE_CODE", "InvoiceBalance.java"), _ev("TEST", "BalanceTest.java")],
        )
        db.commit()
        print(
            "Seed concluído: ana/beto/carla@demo.bsp (senha demo1234!), 6 atoms em finance."
        )


if __name__ == "__main__":
    seed()
