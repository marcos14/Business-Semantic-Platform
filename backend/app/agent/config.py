"""Configuração local do agente: um JSON por máquina, criado por `bsp-agent setup`."""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path


def home() -> Path:
    env = os.environ.get("BSP_AGENT_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "bsp-agent"
    return Path.home() / ".config" / "bsp-agent"


@dataclass
class AgentConfig:
    api_url: str = "http://127.0.0.1:8000"
    api_key: str = ""  # credencial criada pelo administrador (client_id.secret)
    name: str = ""  # rótulo desta máquina (informativo)
    cache_dir: str = ""  # clones em cache; vazio = <home>/repos
    claude_executable: str = "claude"
    # Opcional: chave de API exportada SÓ para o processo do harness. Alternativa: deixar
    # ANTHROPIC_API_KEY no ambiente (ou o `claude` logado) e não gravar nada aqui.
    anthropic_api_key: str = ""
    max_usd_per_day: float = 0.0  # estimativa local do próprio claude; 0 = sem teto
    active_hours: list[str] = field(default_factory=list)  # ["12:00-13:30", "18:30-08:00"]
    poll_seconds: int = 15
    # Caminhos locais por source (opcional): {"<source_id>": {"path": "C:/repos/legado"}}.
    # Usado como origem do clone quando a Source não tem git_url alcançável daqui.
    sources: dict[str, dict] = field(default_factory=dict)

    @property
    def repos_dir(self) -> Path:
        return Path(self.cache_dir) if self.cache_dir else home() / "repos"

    @property
    def logs_dir(self) -> Path:
        return home() / "logs"


def config_path() -> Path:
    return home() / "config.json"


def load() -> AgentConfig:
    p = config_path()
    if not p.exists():
        return AgentConfig()
    dados = json.loads(p.read_text(encoding="utf-8"))
    conhecidos = {k: v for k, v in dados.items() if k in AgentConfig.__dataclass_fields__}
    return AgentConfig(**conhecidos)


def save(cfg: AgentConfig) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


# ---------- estado (pausa e gasto do dia) ----------


@dataclass
class AgentState:
    paused: bool = False
    day: str = ""
    usd_today: float = 0.0
    tasks_today: int = 0


def state_path() -> Path:
    return home() / "state.json"


def load_state() -> AgentState:
    p = state_path()
    if not p.exists():
        return AgentState()
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AgentState()
    st = AgentState(**{k: v for k, v in dados.items() if k in AgentState.__dataclass_fields__})
    hoje = date.today().isoformat()
    if st.day != hoje:
        st.day, st.usd_today, st.tasks_today = hoje, 0.0, 0
    return st


def save_state(st: AgentState) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not st.day:
        st.day = date.today().isoformat()
    p.write_text(json.dumps(asdict(st), indent=2), encoding="utf-8")


# ---------- janelas de horário ----------


def _parse_hm(s: str) -> int:
    h, m = s.strip().split(":")
    return int(h) * 60 + int(m)


def within_hours(windows: list[str], now: datetime | None = None) -> bool:
    """True se `now` cai em alguma janela "HH:MM-HH:MM" (pode cruzar a meia-noite).
    Sem janelas = sempre ativo."""
    if not windows:
        return True
    now = now or datetime.now()
    atual = now.hour * 60 + now.minute
    for w in windows:
        try:
            ini, fim = (_parse_hm(x) for x in w.split("-", 1))
        except ValueError:
            continue
        if ini <= fim:
            if ini <= atual < fim:
                return True
        elif atual >= ini or atual < fim:  # cruza a meia-noite
            return True
    return False
