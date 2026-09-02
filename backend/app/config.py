from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração da aplicação. Lê variáveis de ambiente e o .env da raiz do monorepo."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://bsp:bsp@localhost:5432/bsp"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_hours: int = 24
    openrouter_api_key: str = ""


settings = Settings()
