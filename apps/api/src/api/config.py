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
    parsed = int(value)
    return max(minimum, parsed)


@dataclass(frozen=True)
class Settings:
    database_url: str
    db_echo: bool
    rag_source_dir: str
    rag_index_dir: str
    rag_db_path: str
    rag_chunk_size: int
    rag_chunk_overlap: int
    rag_expected_embed_dim: int
    rag_verify_sample_query: str
    ollama_base_url: str
    ollama_model: str
    ollama_fallback_model: str
    ollama_embed_base_url: str
    ollama_embed_model: str
    ollama_timeout_seconds: float
    plc_executor_mode: str
    plc_cli_path: str | None
    plc_cli_timeout_seconds: int
    training_device: str
    training_allow_cpu: bool
    training_artifact_dir: str
    ft_max_seq_length: int
    ft_default_training_method: str
    ft_trainer_backend: str
    ft_allow_smoke_fallback: bool
    ft_smoke_fallback_backend: str
    ft_trainer_model_map_json: str
    ollama_publish_enabled: bool
    ollama_model_namespace: str | None


@lru_cache
def get_settings() -> Settings:
    starter = starter_definitions.get_default_starter()
    primary_dataset = starter_definitions.get_primary_dataset_definition(starter)

    rag_index_dir = os.getenv("RAG_INDEX_DIR", primary_dataset.index_dir)
    rag_db_path = os.getenv("RAG_DB_PATH", str(Path(rag_index_dir) / "rag.db"))
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

    return Settings(
        database_url=os.getenv(
            "API_DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/industrial_ai",
        ),
        db_echo=_to_bool(os.getenv("API_DB_ECHO"), default=False),
        # Host-friendly defaults are relative paths.
        # Containers override these via compose env to /workspace/... paths.
        rag_source_dir=os.getenv("RAG_SOURCE_DIR", primary_dataset.source_dir),
        rag_index_dir=rag_index_dir,
        rag_db_path=rag_db_path,
        rag_chunk_size=_to_int(os.getenv("RAG_CHUNK_SIZE"), default=500, minimum=100),
        rag_chunk_overlap=_to_int(
            os.getenv("RAG_CHUNK_OVERLAP"), default=50, minimum=0
        ),
        rag_expected_embed_dim=_to_int(
            os.getenv("RAG_EXPECTED_EMBED_DIM"),
            default=768,
            minimum=0,
        ),
        rag_verify_sample_query=os.getenv(
            "RAG_VERIFY_SAMPLE_QUERY", "maintenance automation"
        ),
        ollama_base_url=ollama_base_url,
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M"),
        ollama_fallback_model=os.getenv(
            "OLLAMA_FALLBACK_MODEL", "qwen2.5:3b-instruct-q4_K_M"
        ),
        ollama_embed_base_url=os.getenv("OLLAMA_EMBED_BASE_URL", ollama_base_url),
        ollama_embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
        plc_executor_mode=os.getenv("PLC_EXECUTOR_MODE", "stub").strip().lower()
        or "stub",
        plc_cli_path=os.getenv("PLC_CLI_PATH"),
        plc_cli_timeout_seconds=_to_int(
            os.getenv("PLC_CLI_TIMEOUT_SECONDS"),
            default=30,
            minimum=1,
        ),
        training_device=os.getenv("TRAINING_DEVICE", "auto").strip().lower() or "auto",
        training_allow_cpu=_to_bool(os.getenv("TRAINING_ALLOW_CPU"), default=False),
        training_artifact_dir=os.getenv(
            "MODEL_ARTIFACT_DIR", str(PROJECT_ROOT / "data" / "model_artifacts")
        ),
        ft_max_seq_length=_to_int(
            os.getenv("FT_MAX_SEQ_LENGTH"), default=1024, minimum=128
        ),
        ft_default_training_method=os.getenv(
            "FT_DEFAULT_TRAINING_METHOD", "sft_lora"
        ).strip()
        or "sft_lora",
        ft_trainer_backend=os.getenv("FT_TRAINER_BACKEND", "local_peft").strip()
        or "local_peft",
        ft_allow_smoke_fallback=_to_bool(
            os.getenv("FT_ALLOW_SMOKE_FALLBACK"), default=False
        ),
        ft_smoke_fallback_backend=os.getenv(
            "FT_SMOKE_FALLBACK_BACKEND", "deterministic_smoke"
        ).strip()
        or "deterministic_smoke",
        ft_trainer_model_map_json=os.getenv("FT_TRAINER_MODEL_MAP_JSON", "{}"),
        ollama_publish_enabled=_to_bool(
            os.getenv("OLLAMA_PUBLISH_ENABLED"), default=False
        ),
        ollama_model_namespace=os.getenv("OLLAMA_MODEL_NAMESPACE"),
    )
