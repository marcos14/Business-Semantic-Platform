"""Faixas de confiança (PROVISIONAL), perfis de evidência, independência por sítio,
cascata de evidência (estágio 1) e revisão por filtro — etapas A/B + seções 8/9."""

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

FAKE = [sys.executable, str(Path(__file__).parent / "fake_claude.py")]
DOMAIN = "casc"
CAP = "casc-cobranca"


# ---------- kernel puro: sítios, mecanismos e perfis ----------


def _fact(id, symbol=None, start=None, end=None, mech=None, file="Pedido.pas", type="SOURCE_CODE",
          relation="supports", source_id="s1"):
    from app.kernel.confidence import EvidenceFact

    return EvidenceFact(
        id=id, type=type, relation=relation, lineage=f"file:{source_id}:{file}",
        created_by="agent:a", origin="agent", file=file, symbol=symbol,
        start_line=start, end_line=end, mechanism=mech, source_id=source_id,
    )


def test_sitios_no_mesmo_arquivo_valem_com_desconto():
    from app.kernel.confidence import DEFAULT_PROFILE, LEGACY_HOSTILE_PROFILE, compute_score

    hostil = LEGACY_HOSTILE_PROFILE
    um = compute_score([_fact("1", "TFrm.BeforePost", 10, 20, "VALIDATION")], profile=hostil)
    assert um.score == 0.45 and um.profile == "legacy-hostile" and um.engine_version == "v2"
    # mesma rotina = mesmo sítio: não soma
    mesma = compute_score(
        [_fact("1", "TFrm.BeforePost", 10, 20, "VALIDATION"),
         _fact("2", "TFrm.BeforePost", 12, 18, "VALIDATION")],
        profile=hostil,
    )
    assert mesma.score == um.score
    # rotina distinta do mesmo arquivo: desconto (+0,15)
    dois = compute_score(
        [_fact("1", "TFrm.BeforePost", 10, 20, "VALIDATION"),
         _fact("2", "TFrm.BtnClick", 50, 60, "VALIDATION")],
        profile=hostil,
    )
    assert dois.score == 0.60
    # mecanismos distintos (validação + mensagem) somam
    dois_mec = compute_score(
        [_fact("1", "TFrm.BeforePost", 10, 20, "VALIDATION"),
         _fact("2", "TFrm.BtnClick", 50, 60, "MESSAGE")],
        profile=hostil,
    )
    assert dois_mec.score == 0.65
    tres = compute_score(
        [_fact("1", "TFrm.BeforePost", 10, 20, "VALIDATION"),
         _fact("2", "TFrm.BtnClick", 50, 60, "MESSAGE"),
         _fact("3", "TFrm.Calcula", 90, 99, "CALCULATION")],
        profile=hostil,
    )
    assert tres.score == 0.80
    # arquivo distinto vale cheio (+0,25)
    outro = compute_score(
        [_fact("1", "TFrm.BeforePost", 10, 20, "VALIDATION"),
         _fact("2", "TOutro.X", 1, 5, "VALIDATION", file="Outro.pas")],
        profile=hostil,
    )
    assert outro.score == 0.70
    # alcançabilidade não é sítio: sinal próprio (+0,10)
    vivo = compute_score(
        [_fact("1", "TFrm.BeforePost", 10, 20, "VALIDATION"),
         _fact("2", None, 1, 3, "REACHABILITY", file="Erp.dpr")],
        profile=hostil,
    )
    assert vivo.score == 0.55
    # perfil padrão: dois arquivos = 0,40 (compatível com a v1.1)
    padrao = compute_score(
        [_fact("1", "TFrm.BeforePost", 10, 20, "VALIDATION"),
         _fact("2", "TOutro.X", 1, 5, "VALIDATION", file="Outro.pas")],
        profile=DEFAULT_PROFILE,
    )
    assert padrao.score == 0.40
    explicacao = next(s for s in dois.signals if s.name == "number_of_independent_evidence")
    assert "sítio(s) adicional" in explicacao.explanation


def test_faixas_sem_simbolo_colapsam_por_sobreposicao():
    from app.kernel.confidence import LEGACY_HOSTILE_PROFILE, compute_score, sites_by_lineage

    facts = [_fact("1", None, 10, 20), _fact("2", None, 15, 25), _fact("3", None, 100, 110)]
    sitios = sites_by_lineage(facts)
    assert list(sitios.values()) == [["lines:10-25", "lines:100-110"]]
    assert compute_score(facts, profile=LEGACY_HOSTILE_PROFILE).score == 0.60


def test_documento_divergente_nao_e_conflito_no_perfil_hostil():
    from app.kernel.confidence import DEFAULT_PROFILE, LEGACY_HOSTILE_PROFILE, compute_score

    facts = [
        _fact("1", "TFrm.BeforePost", 10, 20, "VALIDATION"),
        _fact("2", None, None, None, None, file="manual.md", type="DOCUMENT",
              relation="contradicts", source_id="docs"),
    ]
    hostil = compute_score(facts, profile=LEGACY_HOSTILE_PROFILE)
    padrao = compute_score(facts, profile=DEFAULT_PROFILE)
    assert hostil.score == 0.40  # 0,45 − 0,05 de divergência documental
    assert padrao.score == 0.0  # 0,20 − 0,30 de conflito
    div = next(s for s in hostil.signals if s.name == "document_divergence")
    assert div.contribution == -0.05
    assert next(s for s in hostil.signals if s.name == "conflict_presence").contribution == 0


def test_consistencia_entre_fontes_distintas():
    from app.kernel.confidence import DEFAULT_PROFILE, compute_score

    mesma_source = [_fact("1", file="a.pas"), _fact("2", file="ddl.sql", type="DATABASE")]
    duas_sources = [
        _fact("1", file="a.pas"),
        _fact("2", file="ddl.sql", type="DATABASE", source_id="db"),
    ]
    r1 = compute_score(mesma_source, profile=DEFAULT_PROFILE)
    r2 = compute_score(duas_sources, profile=DEFAULT_PROFILE)
    assert r2.score - r1.score == pytest.approx(0.10)


def test_simbolo_envolvente_e_mecanismo():
    from app.engines.symbols import enclosing_symbol, infer_mechanism, verify_symbol

    pas = """unit Pedido;
interface
implementation

procedure TFrmPedido.DBGridBeforePost(DataSet: TDataSet);
begin
  if Desconto > 10 then
    raise Exception.Create('Desconto não pode exceder 10%');
end;

function TFrmPedido.CalculaTotal: Double;
begin
  Result := Valor * (1 - Desconto / 100);
end;
""".splitlines()
    assert enclosing_symbol(pas, 8, "Pedido.pas") == "TFrmPedido.DBGridBeforePost"
    assert enclosing_symbol(pas, 13, "Pedido.pas") == "TFrmPedido.CalculaTotal"
    assert enclosing_symbol(pas, 2, "Pedido.pas") is None
    # símbolo informado pelo agente é verificado (aceita o nome sem a classe)
    assert verify_symbol(pas, 8, "Pedido.pas", "DBGridBeforePost") == "TFrmPedido.DBGridBeforePost"
    assert verify_symbol(pas, 8, "Pedido.pas", "OutraRotina") is None
    assert infer_mechanism("raise Exception.Create('Desconto não pode exceder 10%')") == "MESSAGE"
    assert infer_mechanism("select * from pedidos where status = 'A'") == "SQL"
    assert infer_mechanism("Result := Valor * 0.01 * Dias;") == "CALCULATION"
    py = ["def calcula(x):", "    return x * 2", "", "async def outra():", "    pass"]
    assert enclosing_symbol(py, 2, "a.py") == "calcula"
    assert enclosing_symbol(py, 5, "a.py") == "outra"


# ---------- integração: faixa provisória, revisão por filtro, re-roteamento ----------


def _login(client, email, password="s3nha-teste"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def ctx(client):
    from app.create_admin import ensure_admin

    ensure_admin("admin@example.com", "Admin", "admin-s3nha")
    admin = _login(client, "admin@example.com", "admin-s3nha")
    client.post("/admin/domains", json={"slug": DOMAIN, "name": "Cascata"}, headers=admin)
    client.post(
        "/admin/capabilities",
        json={"slug": CAP, "domain_slug": DOMAIN, "name": "Cobrança"},
        headers=admin,
    )
    ctx = {"admin": admin}
    for key, role in [("rev", "reviewer"), ("rev2", "reviewer"), ("own", "decision_owner")]:
        r = client.post(
            "/admin/users",
            json={"email": f"casc-{key}@example.com", "name": key, "password": "s3nha-teste"},
            headers=admin,
        )
        client.post(
            "/admin/role-bindings",
            json={"user_id": r.json()["id"], "role": role, "domain_slug": DOMAIN},
            headers=admin,
        )
        ctx[key] = _login(client, f"casc-{key}@example.com")
    # política por relevância: MEDIUM canônico 70%, provisório 40%, um revisor basta
    r = client.post(
        "/admin/policies",
        json={
            "name": "MEDIUM — um revisor basta", "scope_type": "significance",
            "selector": "MEDIUM", "threshold": 0.70, "provisional_floor": 0.40,
            "min_reviewers": 1, "require_owner_approval": False,
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    assert r.json()["provisional_floor"] == 0.40
    ctx["policy_id"] = r.json()["id"]
    yield ctx
    client.delete(f"/admin/policies/{ctx['policy_id']}", headers=admin)


def _candidato(title, files, significance="MEDIUM", classification=None, risk=None, tests=()):
    from app.db import SessionLocal
    from app.kernel.ir.envelope import AtomKind, Classification, Origin, RiskLevel
    from app.services.evaluation import evaluate_atom
    from app.services.knowledge import create_candidate

    evidence = [
        {"type": "SOURCE_CODE", "location": {"file": f, "start_line": 1, "end_line": 5}}
        for f in files
    ] + [
        {"type": "TEST", "location": {"file": f, "start_line": 1, "end_line": 5}} for f in tests
    ]
    with SessionLocal() as db:
        atom = create_candidate(
            db, actor="agent:code-discovery:test", origin=Origin.AGENT, kind=AtomKind.RULE,
            title=title, domain=DOMAIN, capability=CAP, body={"statement": title},
            classification=Classification(classification) if classification else None,
            risk=RiskLevel(risk) if risk else None,
            significance=significance,
            evidence=evidence,
        )
        db.flush()
        res = evaluate_atom(db, atom.id, trigger="teste")
        db.commit()
        return atom.id, res


def test_dois_arquivos_medium_viram_provisorio_e_um_humano_canonicaliza(client, ctx):
    atom_id, res = _candidato("Desconto máximo de 10% no pedido", ["Pedido.pas", "Venda.pas"])
    assert res["decision"] == "PROVISIONAL" and res["status"] == "PROVISIONAL"
    assert res["score"] == 0.40 and res["policy"]["threshold"] == 0.70

    # não ocupa a Inbox, mas aparece no resumo, no Kanban, na listagem e no context package
    inbox = client.get("/reviews/inbox", headers=ctx["rev"]).json()
    assert atom_id not in [i["id"] for i in inbox["items"]]
    assert inbox["summary"]["provisional"] >= 1
    kb = client.get("/reviews/kanban", params={"domain": DOMAIN}, headers=ctx["rev"]).json()
    assert any(c["id"] == atom_id for c in kb["columns"]["provisional"])
    lista = client.get(
        "/knowledge", params={"status": "PROVISIONAL", "domain": DOMAIN, "significance": "medium"},
        headers=ctx["rev"],
    ).json()
    assert atom_id in [a["id"] for a in lista["items"]]
    pkg = client.get(
        "/context",
        params={"capability": CAP, "include_provisional": True},
        headers=ctx["rev"],
    ).json()
    labels = {i["id"]: i["label"] for i in pkg["rules"]}
    assert labels[atom_id] == "PROVISIONAL" and pkg["stats"]["provisional"] >= 1
    amostra = client.get(
        "/reviews/inbox/audit-sample", params={"domain": DOMAIN, "n": 50}, headers=ctx["rev"]
    ).json()
    assert atom_id in [i["id"] for i in amostra["items"]]

    # um CONFIRM de reviewer basta: a política MEDIUM dispensa o owner
    r = client.post(f"/reviews/{atom_id}/vote", json={"action": "CONFIRM"}, headers=ctx["rev"])
    assert r.status_code == 201, r.text
    atom = client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()
    assert atom["status"] == "CANONICAL"
    hist = client.get(f"/knowledge/{atom_id}/history", headers=ctx["rev"]).json()
    decisao = [e for e in hist["events"] if e["type"] == "DecisionMade"
               and e["payload"].get("by_role") == "policy"]
    assert decisao and "owner dispensado" in decisao[0]["payload"]["reason"]


def test_high_provisorio_exige_owner_e_rejeicao_abre_discussao(client, ctx):
    atom_id, res = _candidato(
        "Comissão de 5% sobre venda à vista", ["Comissao.pas", "Venda.pas"], significance="HIGH"
    )
    assert res["status"] == "PROVISIONAL"  # piso padrão 0,40 (sem política HIGH nos testes)
    client.post(f"/reviews/{atom_id}/vote", json={"action": "CONFIRM"}, headers=ctx["rev"])
    assert client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()["status"] == "PROVISIONAL"
    # voto que não confirma tira da faixa publicada e abre a discussão humana
    # (o REJECT vira evidência contraditória e, como sempre, abre conflito)
    client.post(f"/reviews/{atom_id}/vote", json={"action": "REJECT"}, headers=ctx["rev2"])
    status = client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()["status"]
    assert status in ("IN_REVIEW", "CONFLICTED")
    hist = client.get(f"/knowledge/{atom_id}/history", headers=ctx["rev"]).json()
    trocas = [e["payload"] for e in hist["events"] if e["type"] == "StatusChanged"]
    assert any(t["from"] == "PROVISIONAL" and t["to"] == "IN_REVIEW" for t in trocas)


def test_provisorio_sobe_a_canonico_com_nova_evidencia(client, ctx):
    atom_id, res = _candidato("Juros de 2% ao mês no atraso", ["Juros.pas", "Boleto.pas"])
    assert res["status"] == "PROVISIONAL"
    for ev in (
        {"type": "TEST", "location": {"file": "Juros_test.pas", "start_line": 1, "end_line": 3}},
        {"type": "DOCUMENT", "location": {"file": "docs/juros.md", "start_line": 1, "end_line": 3}},
    ):
        client.post(f"/knowledge/{atom_id}/evidence", json=ev, headers=ctx["rev"])
    s = client.post(f"/knowledge/{atom_id}/evaluate", headers=ctx["rev"]).json()
    assert s["score"] >= 0.70 and s["status"] == "CANONICAL"
    hist = client.get(f"/knowledge/{atom_id}/history", headers=ctx["rev"]).json()
    trocas = [e["payload"] for e in hist["events"] if e["type"] == "StatusChanged"]
    assert "nova evidência" in trocas[-1]["reason"]


def test_intencao_so_com_codigo_tem_teto_provisorio(client, ctx):
    # 3 arquivos + 1 teste = 0,73 >= limiar MEDIUM (0,70), mas só código/teste sustenta a
    # INTENÇÃO: canônico exigiria banco, documento ou humano
    atom_id, res = _candidato(
        "O negócio exige aprovação gerencial acima de R$ 10 mil",
        ["Aprova.pas", "Fluxo.pas", "Alcada.pas"], tests=["Aprova_test.pas"],
        classification="INTENDED_BEHAVIOR",
    )
    assert res["score"] >= 0.70 and res["status"] == "PROVISIONAL"
    assert "teto provisório" in res["reason"]
    # o mesmo, OBSERVED, canonicaliza
    _, res2 = _candidato(
        "O sistema exige aprovação gerencial acima de R$ 10 mil",
        ["Aprova.pas", "Fluxo.pas", "Alcada.pas"], tests=["Aprova_test.pas"],
        classification="OBSERVED_BEHAVIOR",
    )
    assert res2["status"] == "CANONICAL"


def test_revisao_por_filtro_em_lote(client, ctx):
    a, _ = _candidato("Frete grátis acima de R$ 500", ["Frete.pas", "Pedido.pas"])
    b, _ = _candidato("Frete cobrado por faixa de CEP", ["Frete.pas", "Cep.pas"])
    r = client.post(
        "/reviews/inbox/bulk",
        json={"atom_ids": [a, b, "NAO.EXISTE.RULE.0001"], "action": "CONFIRM"},
        headers=ctx["rev"],
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] == 2 and d["failed"] == 1
    assert {x["status"] for x in d["results"] if x["ok"]} == {"CANONICAL"}


def test_reroute_dos_pendentes_sem_voto(client, ctx):
    from app.db import SessionLocal
    from app.kernel.ir.envelope import Origin
    from app.services.knowledge import add_evidence
    from app.services.triage import reevaluate_pending

    atom_id, res = _candidato("Bloqueio de venda para cliente inadimplente", ["Cliente.pas"])
    assert res["status"] == "NEEDS_HUMAN_REVIEW"  # 1 arquivo = 0,20 < piso
    with SessionLocal() as db:
        add_evidence(
            db, atom_id, actor="agent:code-discovery:test", origin=Origin.AGENT,
            type="SOURCE_CODE", location={"file": "Venda.pas", "start_line": 1, "end_line": 4},
        )
        db.commit()
        r = reevaluate_pending(db, domain=DOMAIN)
    assert r["considered"] >= 1 and r["provisional"] >= 1
    assert client.get(f"/knowledge/{atom_id}", headers=ctx["rev"]).json()["status"] == "PROVISIONAL"
    # atom votado nunca é tocado
    r2 = client.post("/discovery/reroute", json={"domain": DOMAIN}, headers=ctx["admin"])
    assert r2.status_code == 200 and r2.json()["considered"] == 0


def test_perfil_de_evidencia_por_domain(client, ctx):
    r = client.get("/admin/evidence-profiles", headers=ctx["admin"]).json()
    assert {p["name"] for p in r} == {"default", "legacy-hostile"}
    url = f"/admin/domains/{DOMAIN}"
    r = client.patch(url, json={"evidence_profile": "legacy-hostile"}, headers=ctx["admin"])
    assert r.status_code == 200 and r.json()["evidence_profile"] == "legacy-hostile"
    try:
        atom_id, res = _candidato("Um arquivo basta para provisório no legado", ["Unico.pas"])
        assert res["profile"] == "legacy-hostile"
        assert res["score"] == 0.45 and res["status"] == "PROVISIONAL"
        conf = client.get(f"/knowledge/{atom_id}/confidence", headers=ctx["rev"]).json()
        assert conf["profile"] == "legacy-hostile"
    finally:
        client.patch(url, json={"evidence_profile": None}, headers=ctx["admin"])
    r = client.patch(url, json={"evidence_profile": "inexistente"}, headers=ctx["admin"])
    assert r.status_code == 422


# ---------- cascata: duplicata vira reforço, variante, busca por prioridade ----------


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "legado"
    r.mkdir()
    (r / "billing.go").write_text(
        "package billing\n\n// JurosDiarios aplica 1% ao dia apos o vencimento\n"
        "func JurosDiarios(valor float64, diasAtraso int) float64 {\n"
        "    return valor * 0.01 * float64(diasAtraso)\n}\n",
        encoding="utf-8",
    )
    (r / "billing_test.go").write_text(
        "package billing\n// TestJuros garante 1% ao dia\nfunc TestJuros(t *testing.T) {\n"
        "    // asserção de juros\n}\n",
        encoding="utf-8",
    )
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "-A"], ["commit", "-q", "-m", "init"]):
        subprocess.run(["git", *args], cwd=r, check=True, capture_output=True)
    return r


@pytest.fixture()
def fonte(client, ctx, repo, monkeypatch, tmp_path):
    from app.config import settings
    from app.db import SessionLocal
    from app.models.knowledge import Source

    monkeypatch.setattr(settings, "discovery_logs_dir", str(tmp_path / "logs"))
    with SessionLocal() as db:
        src = Source(type="source_code", name=f"casc-{uuid.uuid4().hex[:6]}",
                     repository=str(repo), created_by="teste")
        db.add(src)
        db.commit()
        return src.id


def test_duplicata_exata_reforca_em_vez_de_descartar(client, fonte, monkeypatch):
    from app.db import SessionLocal
    from app.models.knowledge import Evidence, EvidenceLink, KnowledgeAtom
    from app.services.discovery import run_discovery

    monkeypatch.setenv("FAKE_SCENARIO", "discovery_dup")
    with SessionLocal() as db:
        run = run_discovery(
            db, source_id=fonte, agent="code", domain=DOMAIN, capability=CAP,
            actor="teste", executable=FAKE, timeout_min=2,
        )
        assert run.status == "succeeded", run.error
        assert run.candidates_created == 1
        assert run.duplicates_skipped == 1
        assert run.reinforcements == 1  # a evidência da duplicata virou sítio novo
        atom = db.scalar(
            select(KnowledgeAtom).where(
                KnowledgeAtom.domain == DOMAIN,
                KnowledgeAtom.title == "Boleto vencido acumula juros diários",
            )
        )
        evs = db.scalars(
            select(Evidence).join(EvidenceLink, EvidenceLink.evidence_id == Evidence.id)
            .where(EvidenceLink.atom_id == atom.id)
        ).all()
        assert {e.location["file"] for e in evs} == {"billing.go", "billing_test.go"}
        principal = next(e for e in evs if e.location["file"] == "billing.go")
        assert principal.location["symbol"] == "JurosDiarios"  # verificado contra o fonte
        assert principal.meta["mechanism"] == "CALCULATION"
        # 2 linhagens (0,40) + 2 tipos (0,05) + teste (0,08) = 0,53 → provisório (HIGH, piso 0,40)
        assert atom.confidence == pytest.approx(0.53)
        assert atom.status == "PROVISIONAL"


def test_variante_nao_e_suporte_nem_conflito(client, fonte, monkeypatch):
    from app.db import SessionLocal
    from app.models.knowledge import AtomRelation, DomainEvent, EvidenceLink, KnowledgeAtom
    from app.services.discovery import run_corroboration, run_discovery, select_evidence_targets

    monkeypatch.setenv("FAKE_SCENARIO", "discovery_ok")
    with SessionLocal() as db:
        run_discovery(db, source_id=fonte, agent="code", domain=DOMAIN, capability=CAP,
                      actor="teste", executable=FAKE, timeout_min=2)
        atom = db.scalar(
            select(KnowledgeAtom).where(
                KnowledgeAtom.domain == DOMAIN,
                KnowledgeAtom.title == "Boleto vencido acumula juros diários",
            )
        )
        atom_id = atom.id
        n_antes = len(list(db.scalars(select(EvidenceLink).where(EvidenceLink.atom_id == atom_id))))
        # seleção por prioridade: HIGH primeiro
        from app.models.knowledge import Source

        src = db.get(Source, fonte)
        alvos = select_evidence_targets(db, source=src, domain=DOMAIN, capability=CAP, commit=None)
        assert alvos and alvos[0].id == atom_id

    monkeypatch.setenv("FAKE_SCENARIO", "corrob_variant")
    monkeypatch.setenv("FAKE_ATOM_ID", atom_id)
    with SessionLocal() as db:
        run = run_corroboration(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, actor="teste",
            executable=FAKE, timeout_min=2,
        )
        assert run.status == "succeeded", run.error
        assert run.model == "sonnet"  # corroboração usa o modelo mais barato por padrão
        # original intocado; regra irmã criada e ligada por VARIANT_OF; question aberta
        n_depois = len(list(db.scalars(
            select(EvidenceLink).where(EvidenceLink.atom_id == atom_id)
        )))
        assert n_depois == n_antes
        rel = db.scalar(
            select(AtomRelation).where(
                AtomRelation.to_atom == atom_id, AtomRelation.type == "VARIANT_OF"
            )
        )
        assert rel is not None
        irma = db.get(KnowledgeAtom, rel.from_atom)
        assert irma.title == "Orçamento vencido não acumula juros" and irma.significance == "HIGH"
        pergunta = db.scalar(
            select(KnowledgeAtom).where(
                KnowledgeAtom.domain == DOMAIN, KnowledgeAtom.kind == "question",
                KnowledgeAtom.title.ilike("Regra parecida em outro escopo%"),
            )
        )
        assert pergunta is not None
        buscado = db.scalar(
            select(DomainEvent).where(
                DomainEvent.event_type == "EvidenceSearched", DomainEvent.atom_id == atom_id
            )
        )
        assert buscado is not None and buscado.payload["verdict"] == "SIMILAR_DIFFERENT_SCOPE"
        # já buscado neste commit: não entra de novo na seleção
        src = db.get(Source, fonte)
        alvos = select_evidence_targets(
            db, source=src, domain=DOMAIN, capability=CAP, commit=run.commit
        )
        assert atom_id not in [a.id for a in alvos]


def test_busca_de_evidencia_em_lotes_para_quando_esgota(client, fonte, monkeypatch):
    from app.db import SessionLocal
    from app.models.knowledge import Evidence, EvidenceLink, KnowledgeAtom
    from app.services.discovery import run_discovery, run_evidence_search

    monkeypatch.setenv("FAKE_SCENARIO", "discovery_ok")
    with SessionLocal() as db:
        run_discovery(db, source_id=fonte, agent="code", domain=DOMAIN, capability=CAP,
                      actor="teste", executable=FAKE, timeout_min=2)
        atom = db.scalar(
            select(KnowledgeAtom).where(
                KnowledgeAtom.domain == DOMAIN,
                KnowledgeAtom.title == "Boleto vencido acumula juros diários",
            )
        )
        atom_id = atom.id
    monkeypatch.setenv("FAKE_SCENARIO", "corrob_ok")
    monkeypatch.setenv("FAKE_ATOM_ID", atom_id)
    with SessionLocal() as db:
        r = run_evidence_search(
            db, source_id=fonte, domain=DOMAIN, capability=CAP, actor="teste",
            max_batches=3, executable=FAKE, timeout_min=2,
        )
        assert r["batches"] == 1 and r["status"] == "exhausted"  # 2º lote: nada elegível
        evs = db.scalars(
            select(Evidence).join(EvidenceLink, EvidenceLink.evidence_id == Evidence.id)
            .where(EvidenceLink.atom_id == atom_id)
        ).all()
        assert "billing_test.go" in {e.location["file"] for e in evs}
