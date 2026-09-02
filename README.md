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

## Discovery (harness Claude Code)

O discovery roda **no host** (onde o CLI `claude` está logado), nunca no container.
Registre a fonte legada em `/sources` (admin) e então:

```sh
cd backend
# execução direta
uv run python -m app.discovery_cli run --source-name <nome> --agent code \
    --domain <domain> --capability <cap> --scope "<módulos prioritários>" --budget 5

# ou via fila (a API enfileira em POST /discovery/runs; consuma no host):
uv run procrastinate --app=app.jobs.job_app worker --queues discovery
```

Agentes: `code` (código-fonte), `test` (testes automatizados), `corroboration`
(segunda opinião independente sobre candidates existentes, §88). Cada run fica
auditado em `/discovery/runs` (custo US$, commit, versão do CLI, log `.jsonl`).
Candidates entram no funil normal: evidence verificada contra o commit →
confidence → auto-approval ou Inbox de revisão.

Validação do repositório canônico: `uv run semantic compile`.
Seed de demonstração: `python -m app.seed_demo` (ana/beto/carla@demo.bsp, senha demo1234!).
