"""Acompanhamento da fila de discovery (/discovery/queue): leitura e cancelamento.

O banco de teste NÃO tem o schema do procrastinate (só o worker o aplica), então o
endpoint precisa degradar para `schema_missing` em vez de estourar 500. Quando o schema
existe, criamos jobs direto na tabela para exercitar listagem e cancelamento.
"""

import pytest
from sqlalchemy import text


def _login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin(client):
    from app.create_admin import ensure_admin

    ensure_admin("fila-admin@example.com", "Fila", "fila-s3nha-teste")
    return _login(client, "fila-admin@example.com", "fila-s3nha-teste")


def _schema_presente() -> bool:
    from app.db import SessionLocal

    with SessionLocal() as db:
        return bool(
            db.execute(text("select to_regclass('procrastinate_jobs') is not null")).scalar()
        )


def test_queue_exige_autenticacao(client):
    assert client.get("/discovery/queue").status_code == 401


def test_queue_degrada_sem_schema_ou_lista(client, admin):
    r = client.get("/discovery/queue", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["queue"] == "discovery"
    assert isinstance(d["jobs"], list)
    assert d["pending"] == d["by_status"].get("todo", 0)
    if not _schema_presente():
        assert d["schema_missing"] is True
        assert d["workers_alive"] == 0


def test_release_exige_admin_e_degrada_sem_schema(client, admin):
    assert client.post("/discovery/queue/release").status_code == 401
    r = client.post("/discovery/queue/release", json={}, headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["released"] >= 0
    if not _schema_presente():
        assert d["schema_missing"] is True


def test_cancelar_job_inexistente_ou_sem_schema_da_404(client, admin):
    r = client.post("/discovery/queue/999999/cancel", headers=admin)
    assert r.status_code == 404, r.text


def test_listagem_e_cancelamento_com_schema(client, admin):
    from app.db import SessionLocal

    if not _schema_presente():
        pytest.skip("schema do procrastinate ausente no DB de teste")

    with SessionLocal() as db:
        job_id = db.execute(
            text(
                "insert into procrastinate_jobs (queue_name, task_name, args) "
                "values ('discovery', 'jobs.run_discovery', '{\"agent\": \"code\"}') returning id"
            )
        ).scalar()
        db.commit()

    d = client.get("/discovery/queue", headers=admin).json()
    assert d["schema_missing"] is False
    meu = next(j for j in d["jobs"] if j["id"] == job_id)
    assert meu["status"] == "todo" and meu["args"]["agent"] == "code"
    assert d["pending"] >= 1

    # agendado para o futuro → aparece em scheduled_future; release antecipa
    with SessionLocal() as db:
        db.execute(
            text("update procrastinate_jobs set scheduled_at = now() + interval '2 hours' "
                 "where id = :id"),
            {"id": job_id},
        )
        db.commit()
    d = client.get("/discovery/queue", headers=admin).json()
    assert d["scheduled_future"] >= 1 and d["next_scheduled_at"]
    r = client.post("/discovery/queue/release", json={}, headers=admin)
    assert r.status_code == 200 and r.json()["released"] >= 1
    assert client.get("/discovery/queue", headers=admin).json()["scheduled_future"] == 0

    r = client.post(f"/discovery/queue/{job_id}/cancel", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    # segundo cancelamento: não está mais em `todo`
    assert client.post(f"/discovery/queue/{job_id}/cancel", headers=admin).status_code == 409
