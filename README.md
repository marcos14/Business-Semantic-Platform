# Business Semantic Platform (BSP)

Plataforma para reconstrução semântica de sistemas legados: discovery automatizado,
avaliação de confiança, governança humana seletiva e publicação canônica.

- **PRD:** [docs/prds/](docs/prds/)
- **Arquitetura:** [docs/architecture/proposta-arquitetural-mvp.md](docs/architecture/proposta-arquitetural-mvp.md)
- **Plano de implementação:** [docs/plans/plano-implementacao-mvp.md](docs/plans/plano-implementacao-mvp.md)

## Estrutura

```text
backend/         API FastAPI + worker (Python 3.12, uv, SQLAlchemy 2, Procrastinate)
frontend/        Web (Next.js + TypeScript, pnpm)
canonical-repo/  Repositório Git dedicado ao conhecimento canônico (YAML)
docs/            PRD, arquitetura, planos
```

## Como rodar (dev)

Pré-requisitos: Docker, uv, Node 22+ com pnpm.

```sh
cp .env.example .env    # e preencha OPENROUTER_API_KEY
docker compose up -d    # db + api + worker + web
```

- Web: http://localhost:3000
- API: http://localhost:8000 (docs em /docs)

Primeiro administrador:

```sh
docker compose exec api python -m app.create_admin admin@suaempresa.com "Admin" "uma-senha-forte"
```

## Desenvolvimento local (sem containers de app)

```sh
docker compose up -d db

cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload   # API em :8000

cd ../frontend
pnpm install
pnpm dev                               # Web em :3000
```

Testes e lint do backend:

```sh
cd backend
uv run ruff check .
uv run pytest
```
