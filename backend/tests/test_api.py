"""Testes de integração da API (exigem Postgres; ver conftest)."""


def _login(client, email: str, password: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_login_invalido(client):
    r = client.post("/auth/login", json={"email": "nao@existe.com", "password": "x" * 8})
    assert r.status_code == 401


def test_rotas_protegidas_sem_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/admin/users").status_code == 401


def test_fluxo_admin_e_rbac(client):
    from app.create_admin import ensure_admin

    ensure_admin("admin@example.com", "Admin", "admin-s3nha")
    admin = _login(client, "admin@example.com", "admin-s3nha")

    # Domain + capability
    assert (
        client.post(
            "/admin/domains", json={"slug": "finance", "name": "Finance"}, headers=admin
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/admin/capabilities",
            json={"slug": "accounts-receivable", "domain_slug": "finance", "name": "AR"},
            headers=admin,
        ).status_code
        == 201
    )

    # Usuária reviewer escopada em finance
    r = client.post(
        "/admin/users",
        json={"email": "ana@example.com", "name": "Ana", "password": "ana-s3nha!"},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    ana_id = r.json()["id"]
    r = client.post(
        "/admin/role-bindings",
        json={"user_id": ana_id, "role": "reviewer", "domain_slug": "finance"},
        headers=admin,
    )
    assert r.status_code == 201, r.text

    # /auth/me reflete o binding escopado
    ana = _login(client, "ana@example.com", "ana-s3nha!")
    me = client.get("/auth/me", headers=ana).json()
    assert me["bindings"] == [{"role": "reviewer", "domain": "finance", "capability": None}]

    # RBAC: reviewer não acessa admin (403); admin acessa
    assert client.get("/admin/users", headers=ana).status_code == 403
    assert client.get("/admin/users", headers=admin).status_code == 200


def test_binding_capability_de_outro_domain_rejeitado(client):
    from app.create_admin import ensure_admin

    ensure_admin("admin@example.com", "Admin", "admin-s3nha")
    admin = _login(client, "admin@example.com", "admin-s3nha")
    client.post("/admin/domains", json={"slug": "mfg", "name": "Manufacturing"}, headers=admin)

    r = client.post(
        "/admin/users",
        json={"email": "beto@example.com", "name": "Beto", "password": "beto-s3nha"},
        headers=admin,
    )
    beto_id = r.json()["id"]
    # capability accounts-receivable pertence a finance, não a mfg
    r = client.post(
        "/admin/role-bindings",
        json={
            "user_id": beto_id,
            "role": "decision_owner",
            "domain_slug": "mfg",
            "capability_slug": "accounts-receivable",
        },
        headers=admin,
    )
    assert r.status_code == 422
