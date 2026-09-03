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

Logado como administrador, cadastre domains e capabilities na tela **Admin** (`/admin`)
e as fontes legadas em **Sources** (`/sources`).

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

### Inventário + discovery dirigido (repositórios grandes)

Em vez de soltar o agente no repositório inteiro, o fluxo recomendado é em dois passos,
ambos disparáveis na tela **Sources** (ou pela CLI abaixo) e acompanhados em **Discovery**:

1. **Inventário** — enumeramos os arquivos-fonte (por extensão, sem binários), montamos
   lotes que cabem no prompt com o conteúdo embutido e o harness devolve, por arquivo, um
   resumo de negócio e a ligação com as capabilities do domain (relevância 1-3).
   Capabilities encontradas no código sem cadastro viram sugestões (botão "Criar capability").
2. **Campanha dirigida** — para uma capability, cada arquivo inventariado vira um turno do
   harness com o conteúdo numerado embutido (arquivos grandes são fatiados em faixas). O
   agente pode pedir follow-ups em arquivos relacionados, que entram na mesma campanha.

```sh
cd backend
uv run python -m app.discovery_cli inventory --source-name <nome> --domain <domain> [--prefix ADM001/] [--max-files 200]
uv run python -m app.discovery_cli campaign  --source-name <nome> --domain <domain> --capability <cap> [--min-relevance 2] [--budget 3]
```

O harness roda **direto no repositório original** (`DISCOVERY_WORKSPACE_MODE=inplace`,
padrão): só ferramentas de leitura (Read/Grep/Glob, sem Bash) e `git status` fotografado
antes e depois do run — qualquer alteração marca o run como "workspace sujo". Use
`DISCOVERY_WORKSPACE_MODE=clone` para voltar ao clone descartável por run. A Source pode
apontar para um subdiretório do repositório git (ex.: `<repo>/source`).

Outras variáveis: `DISCOVERY_SOURCE_EXTENSIONS` (o que conta como fonte),
`INVENTORY_BATCH_CHARS` (tamanho do lote), `DISCOVERY_CHUNK_LINES` (faixa por turno),
`DISCOVERY_FOLLOWUPS_MAX` (follow-ups por campanha).

Validação do repositório canônico: `uv run semantic compile`.
Seed de demonstração: `python -m app.seed_demo` (ana/beto/carla@demo.bsp, senha demo1234!).
