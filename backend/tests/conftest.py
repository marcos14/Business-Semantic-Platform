import os

# Ambiente de teste ANTES de qualquer import de app.*
os.environ.setdefault("JWT_SECRET", "test-secret-com-32-bytes-ou-mais-0123456789")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://bsp:bsp@localhost:5432/bsp_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def _ensure_test_db() -> bool:
    """Cria o database de teste se o servidor estiver acessível; False se indisponível."""
    url = make_url(TEST_DATABASE_URL)
    try:
        admin = create_engine(
            url.set(database="postgres"),
            isolation_level="AUTOCOMMIT",
            connect_args={"connect_timeout": 2},
        )
        with admin.connect() as conn:
            exists = conn.execute(
                text("select 1 from pg_database where datname = :n"), {"n": url.database}
            ).scalar()
            if not exists:
                conn.execute(text(f'create database "{url.database}"'))
        admin.dispose()
        return True
    except Exception:
        return False


DB_AVAILABLE = _ensure_test_db()


@pytest.fixture(scope="session")
def client():
    if not DB_AVAILABLE:
        pytest.skip("Postgres indisponível — testes de integração pulados")
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app

    with engine.begin() as conn:
        conn.execute(text("create extension if not exists pg_trgm"))
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("drop type if exists role cascade"))
    Base.metadata.create_all(engine)

    with TestClient(app) as c:
        yield c
