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
    rag_chunk_size: int
    rag_chunk_overlap: int
    training_artifact_dir: str
    ft_max_seq_length: int
    ft_default_training_method: str
    ft_mlx_iters: int
    ft_mlx_steps_per_eval: int
    ft_mlx_val_batches: int
    ft_mlx_save_every: int
    ft_mlx_lora_layers: int
    ft_trainer_backend: str
    ft_allow_smoke_fallback: bool
    ft_smoke_fallback_backend: str
    ft_trainer_model_map_json: str
    adapter_publish_enabled: bool
    mlx_model_namespace: str | None
    lmstudio_base_url: str
    lmstudio_chat_model: str
    lmstudio_embed_model: str
    lmstudio_timeout_seconds: float
    lmstudio_models_dir: str


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
        training_artifact_dir=os.getenv(
            "MODEL_ARTIFACT_DIR", str(PROJECT_ROOT / "data" / "model_artifacts")
        ),
        ft_max_seq_length=_to_int(
            os.getenv("FT_MAX_SEQ_LENGTH"), default=1024, minimum=128
        ),
        ft_default_training_method=os.getenv(
            "FT_DEFAULT_TRAINING_METHOD", "sft_qlora"
        ).strip()
        or "sft_qlora",
        ft_mlx_iters=_to_int(os.getenv("FT_MLX_ITERS"), default=1000, minimum=10),
        ft_mlx_steps_per_eval=_to_int(
            os.getenv("FT_MLX_STEPS_PER_EVAL"), default=200, minimum=1
        ),
        ft_mlx_val_batches=_to_int(
            os.getenv("FT_MLX_VAL_BATCHES"), default=10, minimum=1
        ),
        ft_mlx_save_every=_to_int(
            os.getenv("FT_MLX_SAVE_EVERY"), default=500, minimum=1
        ),
        ft_mlx_lora_layers=_to_int(
            os.getenv("FT_MLX_LORA_LAYERS"), default=16, minimum=1
        ),
        ft_trainer_backend=os.getenv("FT_TRAINER_BACKEND", "mlx_qlora").strip()
        or "mlx_qlora",
        ft_allow_smoke_fallback=_to_bool(
            os.getenv("FT_ALLOW_SMOKE_FALLBACK"), default=False
        ),
        ft_smoke_fallback_backend=os.getenv(
            "FT_SMOKE_FALLBACK_BACKEND", "deterministic_smoke"
        ).strip()
        or "deterministic_smoke",
        # Default map so the demo's Train button works out of the box: the
        # default chat model `qwen3.5-4b-mlx` resolves to a tiny MLX
        # checkpoint that brew `mlx_lm.lora` can download cleanly on first
        # use. Reviewers can extend the map via env for other base models.
        ft_trainer_model_map_json=os.getenv(
            "FT_TRAINER_MODEL_MAP_JSON",
            '{"qwen3.5-4b-mlx":"mlx-community/Qwen2.5-0.5B-Instruct-4bit"}',
        ),
        adapter_publish_enabled=_to_bool(
            os.getenv("ADAPTER_PUBLISH_ENABLED"), default=False
        ),
        # Default the namespace so publish builds a usable
        # `candidate_model_name` (`<namespace>/<artifact_root>`) out of the
        # box. Without this, publish always 409s with "publish manifest
        # does not include a candidate serving model name" until the
        # reviewer sets `MLX_MODEL_NAMESPACE` by hand.
        mlx_model_namespace=os.getenv("MLX_MODEL_NAMESPACE", "demo"),
        # LM Studio settings
        lmstudio_base_url=os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
        lmstudio_chat_model=os.getenv("LMSTUDIO_CHAT_MODEL", ""),
        lmstudio_embed_model=os.getenv("LMSTUDIO_EMBED_MODEL", ""),
        lmstudio_timeout_seconds=float(os.getenv("LMSTUDIO_TIMEOUT_SECONDS", "600")),
        lmstudio_models_dir=os.getenv(
            "LMSTUDIO_MODELS_DIR",
            str(Path.home() / ".lmstudio" / "models"),
        ),
    )
