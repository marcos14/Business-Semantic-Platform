from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração da aplicação. Lê variáveis de ambiente e o .env da raiz do monorepo."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://bsp:bsp@localhost:5432/bsp"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_hours: int = 24
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # --- Modelos (um por finalidade; todos sobrescrevíveis no .env) ---
    # Análises via API OpenRouter: tradução de evidence para negócio, detecção de conflitos,
    # decomposição de regras, avaliador (LLM-judge). NÃO é o harness.
    openrouter_model: str = "openai/gpt-5.6-luna"
    # Harness Claude Code (discovery, inventário, corroboração): usa a assinatura do `claude`
    # logado na máquina, não a OpenRouter. Aliases do CLI: opus | sonnet | haiku.
    harness_model: str = "opus"
    harness_effort: str = "high"
    harness_inventory_effort: str = "medium"  # inventário é classificação: effort menor basta
    harness_probe_model: str = "haiku"  # sonda de franquia: o mais barato possível
    # Repositório git dedicado do conhecimento canônico (D3); env: CANONICAL_REPO_PATH
    canonical_repo_path: str = str(Path(__file__).resolve().parents[2] / "canonical-repo")
    # Logs .jsonl dos runs do harness (audit §87); env: DISCOVERY_LOGS_DIR
    discovery_logs_dir: str = str(Path(__file__).resolve().parents[1] / "logs")

    # --- Discovery ---
    # inplace: harness lê o repositório original (só ferramentas de leitura, sem Bash);
    # clone: cópia descartável por run (mais lenta em repositórios grandes).
    discovery_workspace_mode: str = "inplace"
    # Extensões consideradas "fonte" no inventário (binários/forms ficam de fora).
    # (.dpk/.dpr/.dfm ficam de fora: pacote, projeto e layout não carregam regra de negócio)
    discovery_source_extensions: str = (
        ".pas,.inc,.java,.kt,.cs,.vb,.go,.py,.rb,.php,.ts,.tsx,.js,.mjs,"
        ".sql,.prw,.tlpp,.c,.cpp,.h,.cbl,.cob,.rs,.scala,.groovy,.swift"
    )
    # Inventário: quantos caracteres de fonte por run do harness e teto por arquivo.
    inventory_batch_chars: int = 120_000
    inventory_file_max_chars: int = 30_000
    # Discovery dirigido: arquivos maiores que isso viram vários turnos (um por faixa).
    discovery_chunk_lines: int = 1200
    # Follow-ups que um run dirigido pode gerar por campanha (limite de expansão).
    discovery_followups_max: int = 30

    # Régua de relevância: candidate LOW nunca vai a revisão humana — auto-aprova se a
    # confiança passar deste limiar (menor que o da política) ou fica aguardando evidência.
    low_significance_threshold: float = 0.60

    # --- Embeddings (pgvector) ---
    # openrouter | fake (testes, determinístico) | off (sem recuperação vetorial)
    embedding_provider: str = "openrouter"
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dim: int = 1536
    # Quantos candidates existentes vão no prompt de cada turno dirigido (os mais próximos).
    retrieval_top_k: int = 20
    # Similaridade de cosseno: >= skip → mesma afirmação (não cria); >= flag → cria e marca
    # como potencial duplicata. Calibrado para text-embedding-3-small em português.
    dedup_skip_similarity: float = 0.93
    dedup_flag_similarity: float = 0.55


settings = Settings()
