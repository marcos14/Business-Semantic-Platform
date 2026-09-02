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


settings = Settings()
