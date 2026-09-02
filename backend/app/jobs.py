import procrastinate

from app.config import settings


def _pg_conninfo(url: str) -> str:
    """Converte a URL SQLAlchemy (postgresql+psycopg://) para conninfo psycopg puro."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


job_app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=_pg_conninfo(settings.database_url))
)


@job_app.task(name="jobs.ping")
def ping() -> str:
    return "pong"
