from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração da aplicação. Lê variáveis de ambiente e o .env da raiz do monorepo."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://bsp:bsp@localhost:5432/bsp"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_hours: int = 24
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-opus-5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
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


settings = Settings()
