"""Export canônico YAML+Git, `semantic compile`, versionamento e supersession (§57, §71-§72)."""

import subprocess

import pytest

from app.cli import main as cli_main


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "canonical"
    r.mkdir()
    _git(tmp_path, "init", "-b", "main", str(r))
    _git(r, "config", "user.email", "teste@local")
    _git(r, "config", "user.name", "Teste")
    return r


def _canonicalizar(db, atom_id, actor="owner@example.com"):
    from app.kernel.ir.envelope import LifecycleStatus as S
    from app.services.knowledge import change_status, get_atom

    for novo in [S.READY_FOR_EVALUATION, S.NEEDS_HUMAN_REVIEW, S.IN_REVIEW, S.DECISION_PENDING]:
        atom = get_atom(db, atom_id)
        change_status(
            db, atom_id, actor=actor, new_status=novo, reason="teste",
            expected_lock_version=atom.lock_version,
        )
    atom = get_atom(db, atom_id)
    return change_status(
        db, atom_id, actor=actor, new_status=S.CANONICAL, reason="aprovado",
        expected_lock_version=atom.lock_version, authority_granted=True,
    )


@pytest.fixture()
def dominio_can(client):
    """Domain/capability próprios deste módulo, criados via admin."""
    from app.create_admin import ensure_admin

    ensure_admin("admin@example.com", "Admin", "admin-s3nha")
    r = client.post("/auth/login", json={"email": "admin@example.com", "password": "admin-s3nha"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    client.post("/admin/domains", json={"slug": "can", "name": "Canonical"}, headers=h)
    client.post(
        "/admin/capabilities",
        json={"slug": "exp", "domain_slug": "can", "name": "Export"},
        headers=h,
    )
    return "can"


def _nova_rule_canonical(db, title, atom_id=None):
    from app.kernel.ir.envelope import AtomKind, Origin
    from app.services.knowledge import create_candidate

    atom = create_candidate(
        db,
        actor="agent:test",
        origin=Origin.AGENT,
        kind=AtomKind.RULE,
        title=title,
        domain="can",
        capability="exp",
        scope={"country": "BR"},
        body={"statement": title},
        atom_id=atom_id,
        evidence=[{"type": "SOURCE_CODE", "location": {"file": "x.go", "start_line": 1}}],
    )
    db.flush()
    return _canonicalizar(db, atom.id)


def test_export_compile_new_version_e_supersession(client, dominio_can, repo):
    from app.canonical.exporter import export_canonical
    from app.db import SessionLocal
    from app.kernel.errors import KernelError
    from app.services.knowledge import (
        atom_history,
        get_atom,
        new_canonical_version,
        supersede_with,
        update_atom,
    )

    with SessionLocal() as db:
        atom = _nova_rule_canonical(db, "Nota cancelada não recebe pagamento")
        atom_id = atom.id
        db.commit()

    # 1. Export determinístico + commit
    with SessionLocal() as db:
        r1 = export_canonical(db, repo, trigger="teste")
    assert r1["changed"] is True and r1["exported"] == 1
    yaml_path = repo / "can" / "exp" / "rule" / f"{atom_id}.yaml"
    assert yaml_path.exists()
    conteudo = yaml_path.read_text(encoding="utf-8")
    assert conteudo.index("id:") < conteudo.index("kind:") < conteudo.index("status:")
    assert "evidence:" in conteudo

    # 2. Idempotência: segundo export sem mudanças não comita
    with SessionLocal() as db:
        r2 = export_canonical(db, repo, trigger="teste")
    assert r2["changed"] is False

    # 3. semantic compile passa (CLI, independente do banco)
    assert cli_main(["compile", str(repo)]) == 0

    # 4. AC-CAN: canonical não é editável direto; muda por new-version
    with SessionLocal() as db:
        atom = get_atom(db, atom_id)
        with pytest.raises(KernelError):
            update_atom(
                db, atom_id, actor="owner@example.com",
                expected_lock_version=atom.lock_version, changes={"description": "x"},
            )
        db.rollback()

    with SessionLocal() as db:
        atom = get_atom(db, atom_id)
        atom = new_canonical_version(
            db, atom_id, actor="owner@example.com",
            expected_lock_version=atom.lock_version,
            changes={"body": {"statement": "Nota cancelada não recebe pagamento nem estorno"}},
            reason="escopo ampliado",
        )
        assert atom.version == 2  # AC-CAN-01
        db.commit()

    with SessionLocal() as db:
        hist = atom_history(db, atom_id)
    versoes = {v["version"] for v in hist["versions"]}
    assert {1, 2} <= versoes  # AC-CAN-02: histórico preservado

    with SessionLocal() as db:
        r3 = export_canonical(db, repo, trigger="new-version")
    assert r3["changed"] is True
    assert "version: 2" in yaml_path.read_text(encoding="utf-8")
    assert cli_main(["compile", str(repo)]) == 0

    # 5. Supersession por outro atom (§72)
    with SessionLocal() as db:
        novo = _nova_rule_canonical(db, "Nota cancelada bloqueia operações financeiras")
        novo_id = novo.id
        atom = get_atom(db, atom_id)
        old = supersede_with(
            db, atom_id, new_atom_id=novo_id, actor="owner@example.com",
            expected_lock_version=atom.lock_version, reason="regra generalizada",
        )
        assert old.status == "SUPERSEDED"
        db.commit()

    with SessionLocal() as db:
        r4 = export_canonical(db, repo, trigger="supersede")
    assert r4["changed"] is True and r4["exported"] == 2
    assert "status: SUPERSEDED" in yaml_path.read_text(encoding="utf-8")
    novo_yaml = (repo / "can" / "exp" / "rule" / f"{novo_id}.yaml").read_text(encoding="utf-8")
    assert f"to: {atom_id}" in novo_yaml and "SUPERSEDES" in novo_yaml
    assert cli_main(["compile", str(repo)]) == 0

    # histórico git: um commit por export com mudança
    log = _git(repo, "log", "--oneline").stdout.strip().splitlines()
    assert len(log) == 3


def test_compile_acusa_repo_invalido(tmp_path):
    from app.canonical.compiler import compile_repo

    ruim = tmp_path / "d" / "c" / "rule"
    ruim.mkdir(parents=True)
    (ruim / "X.Y.RULE.0001.yaml").write_text(
        "id: X.Y.RULE.0001\nkind: rule\ntitle: t\ndomain: d\nstatus: CANONICAL\n"
        "version: 1\nbody: {}\n",  # rule sem statement → BodyValidationError
        encoding="utf-8",
    )
    report = compile_repo(tmp_path)
    assert not report.ok
    assert any("Body inválido" in e for e in report.schema_errors)
    assert cli_main(["compile", str(tmp_path)]) == 1
