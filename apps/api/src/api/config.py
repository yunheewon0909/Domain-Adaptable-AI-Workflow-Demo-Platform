from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from api.services import starter_definitions


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def get_project_root() -> Path:
    return PROJECT_ROOT


def resolve_project_path(value: str | Path) -> Path:
    path = value if isinstance(value, Path) else Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _to_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: str | None, *, default: int, minimum: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, parsed)


def _to_float(value: str | None, *, default: float, minimum: float = 0.0) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(minimum, parsed)


@dataclass(frozen=True)
class Settings:
    database_url: str
    db_echo: bool
    rag_chunk_size: int
    rag_chunk_overlap: int
    # Provider-agnostic runtime selection (ADR 0009). Default provider is the
    # bundled Ollama container; LMSTUDIO_* envs are honored as deprecated
    # fallbacks when the LLM_* equivalents are unset.
    llm_runtime_provider: str
    llm_base_url: str
    llm_chat_model: str
    llm_embed_model: str
    llm_timeout_seconds: float
    # Max wall-clock seconds a single background job (graph indexing / evaluation)
    # may run before its next cooperative checkpoint aborts it (then it is retried
    # while attempts remain). See services/background_runner + jobs.JobControl.
    job_timeout_seconds: float


@lru_cache
def get_settings() -> Settings:
    # Keep starter_definitions import side-effect for app/demo metadata even though
    # the legacy dataset-derived defaults are gone.
    starter_definitions.get_default_starter()

    return Settings(
        database_url=os.getenv(
            "API_DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/industrial_ai",
        ),
        db_echo=_to_bool(os.getenv("API_DB_ECHO"), default=False),
        rag_chunk_size=_to_int(os.getenv("RAG_CHUNK_SIZE"), default=500, minimum=100),
        rag_chunk_overlap=_to_int(
            os.getenv("RAG_CHUNK_OVERLAP"), default=50, minimum=0
        ),
        llm_runtime_provider=_runtime_provider(),
        llm_base_url=_runtime_base_url(),
        llm_chat_model=os.getenv("LLM_CHAT_MODEL") or os.getenv("LMSTUDIO_CHAT_MODEL", ""),
        llm_embed_model=os.getenv("LLM_EMBED_MODEL")
        or os.getenv("LMSTUDIO_EMBED_MODEL", ""),
        llm_timeout_seconds=_to_float(
            os.getenv("LLM_TIMEOUT_SECONDS") or os.getenv("LMSTUDIO_TIMEOUT_SECONDS"),
            default=600.0,
            minimum=1.0,
        ),
        job_timeout_seconds=_to_float(
            os.getenv("FT_JOB_TIMEOUT_SECONDS"),
            default=1800.0,
            minimum=1.0,
        ),
    )


def _runtime_provider() -> str:
    provider = (os.getenv("LLM_RUNTIME_PROVIDER") or "ollama").strip().lower()
    return provider if provider in {"ollama", "openai_compat"} else "ollama"


def _runtime_base_url() -> str:
    """Resolve the runtime base URL with an LMSTUDIO_* deprecated fallback."""
    explicit = os.getenv("LLM_BASE_URL")
    if explicit:
        return explicit
    if _runtime_provider() == "ollama":
        return "http://ollama:11434"
    return os.getenv("LMSTUDIO_BASE_URL") or "http://localhost:1234/v1"
