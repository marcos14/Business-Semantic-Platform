"""Triagem retroativa: pendentes de revisão sem voto recebem relevância e SYSTEMIC/LOW saem
da Inbox pelo roteamento automático. Provider de LLM FALSO (sem rede)."""

import json
import uuid

import pytest

DOMAIN = "tri"
CAP = "tri-cap"


class FakeLLM:
    model = "fake-llm"

    def __init__(self):
        self.calls = 0

    def complete(self, *, system: str, user: str, max_tokens: int = 1024) -> str:
        self.calls += 1
        itens = json.loads(user)["items"]
        out = []
        for it in itens:
            t = (it["title"] + " " + it["statement"]).lower()
            if "obrigat" in t or "data inicial" in t:
                sig = "SYSTEMIC"
            elif "arredond" in t:
                sig = "LOW"
            elif "sem resposta" in t:
                continue  # simula id não devolvido
            else:
                sig = "HIGH"
            out.append({"id": it["id"], "significance": sig, "reason": "teste"})
        return "```json\n" + json.dumps({"items": out}) + "\n```"  # com cerca, como LLMs fazem


@pytest.fixture()
def pendentes(client):
    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, Origin
    from app.models.auth import Capability, Domain
    from app.models.knowledge import Source
    from app.services.evaluation import evaluate_atom
    from app.services.knowledge import create_candidate

    with SessionLocal() as db:
        if db.get(Domain, DOMAIN) is None:
            db.add(Domain(slug=DOMAIN, name="Triagem"))
            db.flush()
        if db.get(Capability, CAP) is None:
            db.add(Capability(slug=CAP, domain_slug=DOMAIN, name="Cap"))
        src = Source(type="source_code", name=f"tri-{uuid.uuid4().hex[:6]}",
                     repository="C:/x", created_by="t")
        db.add(src)
        db.flush()
        ev = [{"type": "SOURCE_CODE", "location": {"file": "a.pas"}, "source_id": src.id}]
        ids = {}
        for chave, titulo, stmt in (
            ("sys", "Campos obrigatórios do cadastro", "Nome e CNPJ são obrigatórios."),
            ("low", "Arredondamento de exibição", "Valores exibidos arredondam em 2 casas."),
            ("high", "Comissão zerada em cancelamento", "Nota cancelada não gera comissão."),
            ("none", "Item sem resposta", "O modelo não devolve este id."),
        ):
            a = create_candidate(db, actor="t", origin=Origin.AGENT, kind=AtomKind.RULE,
                                 title=titulo, domain=DOMAIN, capability=CAP,
                                 body={"statement": stmt}, evidence=ev)
            evaluate_atom(db, a.id, trigger="teste")  # 1 evidência → NEEDS_HUMAN_REVIEW
            ids[chave] = a.id
        db.commit()
        return ids


def test_parse_tolerante():
    from app.services.triage import _parse

    assert _parse('{"items":[{"id":"A","significance":"trivial","reason":"x"}]}') == {
        "A": {"significance": "SYSTEMIC", "reason": "x"}
    }
    assert _parse("```json\n{\"items\":[{\"id\":\"B\",\"significance\":\"HIGH\"}]}\n```")["B"][
        "significance"] == "HIGH"
    assert _parse("lixo {\"items\":[{\"id\":\"C\",\"significance\":\"LOW\"}]} fim")["C"][
        "significance"] == "LOW"
    assert _parse("nada") == {} and _parse('{"items":[{"id":"D","significance":"X"}]}') == {}


def test_triagem_reclassifica_e_reroteia(pendentes, monkeypatch):
    from app.config import settings
    from app.db import SessionLocal
    from app.models.knowledge import KnowledgeAtom
    from app.services.triage import pending_atoms, triage_pending

    monkeypatch.setattr(settings, "embedding_provider", "fake")
    fake = FakeLLM()
    with SessionLocal() as db:
        assert {a.id for a in pending_atoms(db, domain=DOMAIN)} >= set(pendentes.values())

        seco = triage_pending(db, domain=DOMAIN, apply=False, provider=fake)
        assert seco["dry_run"] and seco["classified"] == 3 and seco["unclassified"] == 1
        assert seco["by_significance"]["SYSTEMIC"] == 1 and seco["rerouted"] == 0
        assert db.get(KnowledgeAtom, pendentes["sys"]).status == "NEEDS_HUMAN_REVIEW"

        r = triage_pending(db, domain=DOMAIN, apply=True, provider=fake)
        assert r["classified"] == 3 and r["rerouted"] == 2
        assert r["auto_approved"] == 1 and r["awaiting_evidence"] == 1 and r["still_human"] == 1

        atoms = {k: db.get(KnowledgeAtom, v) for k, v in pendentes.items()}
        assert atoms["sys"].significance == "SYSTEMIC" and atoms["sys"].status == "CANONICAL"
        assert atoms["low"].significance == "LOW" and atoms["low"].status == "CORROBORATING"
        assert atoms["high"].significance == "HIGH" and atoms["high"].status == "NEEDS_HUMAN_REVIEW"
        assert atoms["none"].significance is None and atoms["none"].status == "NEEDS_HUMAN_REVIEW"

        # idempotente: quem já tem relevância não é reconsiderado
        assert pending_atoms(db, domain=DOMAIN) and all(
            a.significance is None for a in pending_atoms(db, domain=DOMAIN)
        )
        r2 = triage_pending(db, domain=DOMAIN, apply=True, provider=fake)
        assert r2["considered"] == 1  # só o "sem resposta"


def test_endpoint_exige_admin(client):
    assert client.post("/discovery/triage", json={}).status_code == 401
