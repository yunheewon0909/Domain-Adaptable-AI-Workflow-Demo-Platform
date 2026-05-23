from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, cast

from api.config import Settings
from api.services.fine_tuning.dataset_formatters import DatasetExportResult


SUPPORTED_REAL_TRAINING_METHODS = {"sft_qlora"}
SUPPORTED_TRAINER_BACKENDS = {"deterministic_smoke", "mlx_qlora"}
DETERMINISTIC_SMOKE_TRAINER_MODEL_NAME = "deterministic-smoke-trainer"
HF_MODEL_RESOLUTION_ERROR_MARKERS = (
    "huggingface.co",
    "huggingface",
    "hf_hub",
    "hfhubhttp",
    "from_pretrained",
    "repositorynotfounderror",
    "revisionnotfounderror",
    "entrynotfounderror",
    "gatedrepoerror",
    "401 client error",
    "404 client error",
    "couldn't connect to 'https://huggingface.co'",
    "can't load tokenizer",
    "can't load the model",
    "is not a local folder and is not a valid model identifier",
)


@dataclass
class TrainingConfig:
    trainer_model_name: str
    base_model_name: str
    training_method: str
    trainer_backend: str
    epochs: float
    learning_rate: float
    batch_size: int
    gradient_accumulation_steps: int
    max_seq_length: int
    lora_r: int
    lora_alpha: int
    lora_dropout: float
    eval_strategy: str
    seed: int
    max_steps: int
    export_merged_model: bool
    per_device_eval_batch_size: int
    # MLX QLoRA-specific
    mlx_iters: int = 1000
    mlx_steps_per_eval: int = 200
    mlx_val_batches: int = 10
    mlx_save_every: int = 500
    mlx_lora_layers: int = 16


@dataclass
class TrainingArtifacts:
    adapter_dir: str
    report_path: str
    merged_model_dir: str | None
    logs_path: str
    metrics: dict[str, Any]
    evaluation: dict[str, Any]
    trainer_backend: str
    trainer_model_name: str
    device: str


def _parse_model_map(raw_value: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FT_TRAINER_MODEL_MAP_JSON must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("FT_TRAINER_MODEL_MAP_JSON must be a JSON object")
    return {str(key): str(value) for key, value in parsed.items() if str(value).strip()}


def resolve_trainer_model_name(
    base_model_name: str,
    hyperparams_json: dict[str, Any],
    settings: Settings,
) -> str:
    explicit = str(hyperparams_json.get("trainer_model_name") or "").strip()
    if explicit:
        return explicit
    model_map = _parse_model_map(settings.ft_trainer_model_map_json)
    if base_model_name in model_map:
        return model_map[base_model_name]
    if "/" in base_model_name:
        return base_model_name
    raise RuntimeError(
        "trainer_model_name is required unless FT_TRAINER_MODEL_MAP_JSON maps the selected base model"
    )


def build_training_config(
    *,
    base_model_name: str,
    training_method: str,
    hyperparams_json: dict[str, Any],
    settings: Settings,
) -> TrainingConfig:
    normalized_method = training_method.strip() or settings.ft_default_training_method
    if normalized_method not in SUPPORTED_REAL_TRAINING_METHODS:
        raise RuntimeError(
            f"unsupported real training method: {normalized_method}. Supported methods: {sorted(SUPPORTED_REAL_TRAINING_METHODS)}"
        )
    trainer_backend = settings.ft_trainer_backend.strip() or "mlx_qlora"
    if trainer_backend not in SUPPORTED_TRAINER_BACKENDS:
        raise RuntimeError(
            f"unsupported trainer backend: {trainer_backend}. Supported backends: {sorted(SUPPORTED_TRAINER_BACKENDS)}"
        )
    return TrainingConfig(
        trainer_model_name=resolve_trainer_model_name(
            base_model_name, hyperparams_json, settings
        ),
        base_model_name=base_model_name,
        training_method=normalized_method,
        trainer_backend=trainer_backend,
        epochs=float(hyperparams_json.get("epochs", 1)),
        learning_rate=float(hyperparams_json.get("learning_rate", 2e-4)),
        batch_size=max(1, int(hyperparams_json.get("batch_size", 1))),
        gradient_accumulation_steps=max(
            1, int(hyperparams_json.get("gradient_accumulation_steps", 1))
        ),
        max_seq_length=max(
            128, int(hyperparams_json.get("max_seq_length", settings.ft_max_seq_length))
        ),
        lora_r=max(1, int(hyperparams_json.get("lora_r", 8))),
        lora_alpha=max(1, int(hyperparams_json.get("lora_alpha", 16))),
        lora_dropout=max(0.0, float(hyperparams_json.get("lora_dropout", 0.05))),
        eval_strategy=str(hyperparams_json.get("eval_strategy", "epoch") or "epoch"),
        seed=int(hyperparams_json.get("seed", 42)),
        max_steps=int(hyperparams_json.get("max_steps", -1)),
        export_merged_model=bool(hyperparams_json.get("export_merged_model", False)),
        per_device_eval_batch_size=max(
            1, int(hyperparams_json.get("per_device_eval_batch_size", 1))
        ),
        mlx_iters=max(10, int(hyperparams_json.get("mlx_iters", settings.ft_mlx_iters))),
        mlx_steps_per_eval=max(
            1, int(hyperparams_json.get("mlx_steps_per_eval", settings.ft_mlx_steps_per_eval))
        ),
        mlx_val_batches=max(
            1, int(hyperparams_json.get("mlx_val_batches", settings.ft_mlx_val_batches))
        ),
        mlx_save_every=max(
            1, int(hyperparams_json.get("mlx_save_every", settings.ft_mlx_save_every))
        ),
        mlx_lora_layers=max(
            1, int(hyperparams_json.get("mlx_lora_layers", settings.ft_mlx_lora_layers))
        ),
    )



def run_training_backend(
    export_result: DatasetExportResult,
    *,
    base_model_name: str,
    training_method: str,
    hyperparams_json: dict[str, Any],
    settings: Settings,
    output_dir: Path,
) -> TrainingArtifacts:
    config = build_training_config(
        base_model_name=base_model_name,
        training_method=training_method,
        hyperparams_json=hyperparams_json,
        settings=settings,
    )
    if config.trainer_backend == "deterministic_smoke":
        return _run_deterministic_smoke_training(
            export_result,
            config=config,
            output_dir=output_dir,
            lineage_backend="deterministic_smoke",
        )
    if config.trainer_backend != "mlx_qlora":
        raise RuntimeError(f"unsupported trainer backend: {config.trainer_backend}")

    try:
        return _run_mlx_qlora_training(
            export_result, config=config, settings=settings, output_dir=output_dir
        )
    except Exception as exc:
        if not _should_use_smoke_fallback(
            exc, hyperparams_json=hyperparams_json, settings=settings
        ):
            raise
        fallback_backend = (
            settings.ft_smoke_fallback_backend.strip() or "deterministic_smoke"
        )
        if fallback_backend != "deterministic_smoke":
            raise RuntimeError(
                f"smoke fallback failed: unsupported fallback backend: {fallback_backend}"
            ) from exc
        try:
            return _run_deterministic_smoke_training(
                export_result,
                config=config,
                output_dir=output_dir,
                lineage_backend="mlx_qlora+smoke_fallback",
                root_cause=str(exc),
            )
        except Exception as fallback_exc:
            raise RuntimeError(
                f"smoke fallback failed after hf_model_download_failure: {fallback_exc}"
            ) from fallback_exc


def is_hf_model_resolution_error(error: str | Exception) -> bool:
    lowered = str(error).strip().lower()
    return any(marker in lowered for marker in HF_MODEL_RESOLUTION_ERROR_MARKERS)


def _should_use_smoke_fallback(
    exc: Exception, *, hyperparams_json: dict[str, Any], settings: Settings
) -> bool:
    if not bool(hyperparams_json.get("smoke_test", False)):
        return False
    if not settings.ft_allow_smoke_fallback:
        return False
    return is_hf_model_resolution_error(exc)


# ---- Deterministic smoke (kept for testing) ---------------------------


def _run_deterministic_smoke_training(
    export_result: DatasetExportResult,
    *,
    config: TrainingConfig,
    output_dir: Path,
    lineage_backend: str,
    root_cause: str | None = None,
) -> TrainingArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    adapter_dir = output_dir / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "training_report.json"
    logs_path = output_dir / "training.log"

    adapter_config = {
        "base_model_name_or_path": config.base_model_name,
        "adapter_type": "deterministic_smoke",
        "training_method": config.training_method,
        "smoke_fallback": True,
    }
    (adapter_dir / "adapter_config.json").write_text(
        json.dumps(adapter_config, indent=2), encoding="utf-8"
    )
    (adapter_dir / "adapters.safetensors").write_bytes(
        b"deterministic-smoke-adapter-placeholder\n"
    )

    metrics = {
        "train_runtime": 0.0,
        "train_loss": 0.0,
        "smoke_fallback_used": True,
        "artifact_validation_only": True,
    }
    evaluation = {
        "status": "not_run",
        "baseline_comparison": "not_implemented",
        "artifact_validation_only": True,
    }
    report_payload = {
        "config": {
            **asdict(config),
            "trainer_backend": lineage_backend,
            "trainer_model_name": DETERMINISTIC_SMOKE_TRAINER_MODEL_NAME,
        },
        "device": "cpu",
        "export": export_result.format_summary,
        "metrics": metrics,
        "evaluation": evaluation,
        "artifacts": {
            "adapter_dir": str(adapter_dir),
            "merged_model_dir": None,
        },
        "smoke_fallback": {
            "used": True,
            "message": "Smoke fallback trainer was used",
            "quality_note": "This validates dataset/export/artifact/registry flow, not model quality",
            "runtime_note": "Use the Mac-native MLX QLoRA path for real trainer validation",
            "root_cause": root_cause,
        },
    }
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    log_lines = [
        f"trainer_backend={lineage_backend}",
        f"trainer_model_name={DETERMINISTIC_SMOKE_TRAINER_MODEL_NAME}",
        "device=cpu",
        f"training_method={config.training_method}",
        "smoke_fallback_used=true",
        "Smoke fallback trainer was used",
        "This validates dataset/export/artifact/registry flow, not model quality",
        "Use the Mac-native MLX QLoRA path for real trainer validation",
    ]
    if root_cause:
        log_lines.append(f"fallback_trigger={root_cause}")
    logs_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    return TrainingArtifacts(
        adapter_dir=str(adapter_dir),
        report_path=str(report_path),
        merged_model_dir=None,
        logs_path=str(logs_path),
        metrics=metrics,
        evaluation=evaluation,
        trainer_backend=lineage_backend,
        trainer_model_name=DETERMINISTIC_SMOKE_TRAINER_MODEL_NAME,
        device="cpu",
    )


# ---- MLX QLoRA backend ------------------------------------------------


_TOKENIZER_AUX_FILES = (
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.json",
    "merges.txt",
    "tokenizer.model",
    "generation_config.json",
)


def _backfill_tokenizer_aux_files(
    *, fused_dir: Path, base_model_repo_id: str, logs_path: Path
) -> None:
    """Copy missing tokenizer aux files from the base model's HF snapshot.

    `mlx_lm.fuse` only emits the core model + tokenizer.json /
    tokenizer_config.json. LM Studio's MLX loader rejects the fused dir
    when `special_tokens_map.json` (or sometimes vocab.json/merges.txt)
    is absent — the symptom reviewers see is "Load failed" in LM Studio's
    UI. Best-effort: if any aux file is missing in the fused dir but
    present in the base model's HF snapshot, copy it across.
    """
    import shutil as _shutil

    if "/" not in base_model_repo_id:
        return
    cache_dir_name = "models--" + base_model_repo_id.replace("/", "--")
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub" / cache_dir_name / "snapshots"
    if not hf_cache.is_dir():
        return
    snapshots = sorted(hf_cache.iterdir())
    if not snapshots:
        return
    snapshot = snapshots[-1]
    copied: list[str] = []
    for filename in _TOKENIZER_AUX_FILES:
        source = snapshot / filename
        if not source.exists():
            continue
        target = fused_dir / filename
        if target.exists():
            continue
        try:
            _shutil.copy2(source, target)
            copied.append(filename)
        except OSError:
            continue
    if copied:
        with logs_path.open("a", encoding="utf-8") as log_fh:
            log_fh.write(
                f"\nbackfilled tokenizer aux from base model snapshot: {', '.join(copied)}\n"
            )


def _tail_text(path: Path, *, max_bytes: int = 2000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-max_bytes:].decode("utf-8", errors="replace").strip()


def _run_mlx_qlora_training(
    export_result: DatasetExportResult,
    *,
    config: TrainingConfig,
    settings: Settings,
    output_dir: Path,
) -> TrainingArtifacts:
    """Run MLX QLoRA training via subprocess (mlx_lm.lora + mlx_lm.fuse).

    Subprocess stdout/stderr is streamed directly to logs_path so memory usage
    is bounded for long runs.
    """
    import shutil
    import subprocess
    import time

    output_dir.mkdir(parents=True, exist_ok=True)
    adapter_dir = output_dir / "adapters"
    fused_dir = output_dir / "fused_model"
    logs_path = output_dir / "training.log"
    report_path = output_dir / "training_report.json"

    # Build MLX training data dir (train.jsonl + valid.jsonl from export)
    if not export_result.train_file:
        raise RuntimeError(
            "MLX QLoRA training requires a non-empty train split in the dataset export."
        )

    mlx_data_dir = output_dir / "mlx_data"
    mlx_data_dir.mkdir(parents=True, exist_ok=True)
    (mlx_data_dir / "train.jsonl").write_bytes(
        Path(export_result.train_file).read_bytes()
    )
    if export_result.val_file:
        (mlx_data_dir / "valid.jsonl").write_bytes(
            Path(export_result.val_file).read_bytes()
        )

    header_lines = [
        "trainer_backend=mlx_qlora",
        f"base_model={config.base_model_name}",
        f"trainer_model={config.trainer_model_name}",
        f"iters={config.mlx_iters}",
        f"batch_size={config.batch_size}",
        f"lora_layers={config.mlx_lora_layers}",
        f"lora_r={config.lora_r}",
        f"learning_rate={config.learning_rate}",
    ]

    lora_exe = shutil.which("mlx_lm.lora")
    if not lora_exe:
        raise RuntimeError(
            "mlx_lm.lora CLI is required. Install with: brew install mlx-lm"
        )
    lora_cmd = [
        lora_exe,
        "--model", config.trainer_model_name,
        "--data", str(mlx_data_dir),
        "--train",
        "--num-layers", str(config.mlx_lora_layers),
        "--batch-size", str(config.batch_size),
        "--iters", str(config.mlx_iters),
        "--steps-per-eval", str(config.mlx_steps_per_eval),
        "--val-batches", str(config.mlx_val_batches),
        "--save-every", str(config.mlx_save_every),
        "--adapter-path", str(adapter_dir),
        "--learning-rate", str(config.learning_rate),
        "--seed", str(config.seed),
        "--max-seq-length", str(config.max_seq_length),
    ]
    header_lines.append("lora_cmd=" + " ".join(str(a) for a in lora_cmd))
    print(f"[MLX QLoRA] Starting training: {' '.join(str(a) for a in lora_cmd)}")

    # Stream lora subprocess output directly to logs_path (bounded memory).
    start = time.monotonic()
    with logs_path.open("w", encoding="utf-8") as log_fh:
        log_fh.write("\n".join(header_lines) + "\n")
        log_fh.write("--- mlx_lm.lora stdout/stderr ---\n")
        log_fh.flush()
        result = subprocess.run(
            lora_cmd, stdout=log_fh, stderr=subprocess.STDOUT
        )
    elapsed = time.monotonic() - start

    with logs_path.open("a", encoding="utf-8") as log_fh:
        log_fh.write(f"\ntraining_elapsed_s={elapsed:.1f}\n")
        log_fh.write(f"training_returncode={result.returncode}\n")

    if result.returncode != 0:
        raise RuntimeError(
            f"MLX QLoRA training failed (exit={result.returncode}): "
            f"{_tail_text(logs_path, max_bytes=500)}"
        )

    adapter_weights = adapter_dir / "adapters.safetensors"
    if not adapter_weights.exists():
        # mlx-lm 0.20+ may use npz format
        adapter_weights = adapter_dir / "adapters.npz"
    if not adapter_weights.exists():
        raise RuntimeError(
            f"MLX QLoRA training completed but adapter not found at {adapter_dir}/*"
        )

    fuse_exe = shutil.which("mlx_lm.fuse")
    if not fuse_exe:
        raise RuntimeError(
            "mlx_lm.fuse CLI is required. Install with: brew install mlx-lm"
        )
    fuse_cmd = [
        fuse_exe,
        "--model", config.trainer_model_name,
        "--adapter-path", str(adapter_dir),
        "--save-path", str(fused_dir),
    ]
    print(f"[MLX QLoRA] Fusing model: {' '.join(fuse_cmd)}")

    with logs_path.open("a", encoding="utf-8") as log_fh:
        log_fh.write(f"\nfusing model to {fused_dir}\n")
        log_fh.write("--- mlx_lm.fuse stdout/stderr ---\n")
        log_fh.flush()
        fuse_result = subprocess.run(
            fuse_cmd, stdout=log_fh, stderr=subprocess.STDOUT
        )

    if fuse_result.returncode != 0:
        raise RuntimeError(
            f"MLX model fusion failed (exit={fuse_result.returncode}): "
            f"{_tail_text(logs_path, max_bytes=500)}"
        )

    # mlx_lm.fuse writes only the core model + tokenizer.json /
    # tokenizer_config.json. LM Studio's MLX loader (and stricter HF
    # transformers builds) also want the auxiliary tokenizer files
    # (`special_tokens_map.json`, `vocab.json`, `merges.txt`,
    # `added_tokens.json`, `tokenizer.model`, `generation_config.json`).
    # Copy them from the base model's HF snapshot if present so the
    # fused dir is a fully-loadable MLX repo.
    _backfill_tokenizer_aux_files(
        fused_dir=fused_dir,
        base_model_repo_id=config.trainer_model_name,
        logs_path=logs_path,
    )

    with logs_path.open("a", encoding="utf-8") as log_fh:
        log_fh.write("\nfusion succeeded\n")

    metrics = {
        "train_runtime_s": round(elapsed, 1),
        "mlx_returncode": result.returncode,
        "training_method": "qlora",
    }
    report_payload = {
        "config": {**asdict(config), "trainer_backend": "mlx_qlora"},
        "device": "mlx",
        "export": export_result.format_summary,
        "metrics": metrics,
        "evaluation": {},
        "artifacts": {
            "adapter_dir": str(adapter_dir),
            "fused_model_dir": str(fused_dir) if fused_dir.exists() else None,
        },
    }
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return TrainingArtifacts(
        adapter_dir=str(adapter_dir),
        report_path=str(report_path),
        merged_model_dir=str(fused_dir) if fused_dir.exists() else None,
        logs_path=str(logs_path),
        metrics=metrics,
        evaluation={},
        trainer_backend="mlx_qlora",
        trainer_model_name=config.trainer_model_name,
        device="mlx",
    )
