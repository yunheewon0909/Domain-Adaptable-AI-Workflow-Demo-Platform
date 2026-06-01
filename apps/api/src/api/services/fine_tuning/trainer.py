from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import re
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


def _is_mlx_model_dir(path: Path) -> bool:
    """Return True if path looks like a loadable MLX model directory."""
    return (path / "config.json").is_file() and (
        (path / "model.safetensors").is_file()
        or (path / "model.npz").is_file()
    )


def _normalize_for_matching(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def _config_id_matches(model_dir: Path, norm_model_base: str) -> bool:
    """Return True if config.json in model_dir identifies the model by norm_model_base."""
    try:
        config = json.loads(
            (model_dir / "config.json").read_text(encoding="utf-8", errors="replace")
        )
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(config, dict):
        return False
    for field in ("_name_or_path", "_hf_model_id", "model_name", "name"):
        value = str(config.get(field) or "")
        if value and norm_model_base in _normalize_for_matching(value):
            return True
    return False


def _is_under_namespace(path: Path, models_root: Path, namespace: str | None) -> bool:
    """Return True if `path` lives directly under `models_root/<namespace>/`.

    Used to skip the platform's own published fine-tuned models when resolving
    a *base* model to train on.  Publishing places fused FT models under
    `<models_root>/<namespace>/<name>` (namespace defaults to "demo"), and
    those dirs fuzzy-match the base name they were derived from — so without
    this guard a retrain of "liquid/lfm2.5-1.2b" can resolve to the previous
    fine-tune and train on top of it instead of the clean base.
    """
    if not namespace:
        return False
    try:
        rel = path.resolve().relative_to(models_root.resolve())
    except (ValueError, OSError):
        return False
    return len(rel.parts) >= 1 and rel.parts[0] == namespace


def _scan_lmstudio_models_for_key(
    model_key: str, *, exclude_namespace: str | None = None
) -> str | None:
    """Walk ~/.lmstudio/models to find an MLX directory matching model_key.

    Called when lms ls reports a path that doesn't exist on disk, which happens
    when LM Studio's index uses a different naming convention than the actual
    directory (e.g. modelKey=liquid/lfm2.5-1.2b but the real dir is
    lmstudio-community/LFM2.5-1.2B-Instruct-MLX-4bit).

    `exclude_namespace` (e.g. the platform publish namespace "demo") skips any
    dir under `<models_root>/<exclude_namespace>/` so we never resolve a base
    model to one of the platform's own published fine-tunes.

    Two-pass strategy:
    1. Parse config.json identity fields (_name_or_path, _hf_model_id, …)
    2. Fuzzy directory name match — model's base name (normalized) is a
       substring of the candidate dir name (normalized).
    """
    models_root = Path.home() / ".lmstudio" / "models"
    if not models_root.is_dir():
        return None

    # Strip publisher prefix: "liquid/lfm2.5-1.2b" → "lfm2.5-1.2b"
    base_name = model_key.rsplit("/", 1)[-1]
    norm_base = _normalize_for_matching(base_name)
    if not norm_base:
        return None

    # Collect valid MLX dirs at 1 and 2 levels deep (covers publisher/model layout)
    valid_dirs: list[Path] = []
    for glob_pattern in ("*/", "*/*/"):
        for subdir in sorted(models_root.glob(glob_pattern)):
            if not (subdir.is_dir() and _is_mlx_model_dir(subdir)):
                continue
            if _is_under_namespace(subdir, models_root, exclude_namespace):
                continue
            valid_dirs.append(subdir)

    # Pass 1: config.json identity fields
    for candidate in valid_dirs:
        if _config_id_matches(candidate, norm_base):
            return str(candidate)

    # Pass 2: directory name substring match
    for candidate in valid_dirs:
        if norm_base in _normalize_for_matching(candidate.name):
            return str(candidate)

    return None


def _resolve_lmstudio_model_path(
    model_key: str, *, exclude_namespace: str | None = None
) -> str | None:
    """Resolve an LM Studio modelKey (e.g. `qwen3.5-4b-mlx`) to the
    absolute on-disk path of its MLX repo directory.

    Lets the trainer use the same model the chat picker selected, so
    "I picked the 4B base in the dropdown" actually trains the 4B
    instead of silently swapping to whatever `FT_TRAINER_MODEL_MAP_JSON`
    maps to.

    Returns None when:
    - `lms` CLI is not on PATH
    - the model is not indexed by LM Studio
    - the resolved path doesn't look like an MLX repo
    """
    import shutil as _shutil
    import subprocess as _subprocess

    lms_exe = _shutil.which("lms") or str(
        Path.home() / ".lmstudio" / "bin" / "lms"
    )
    if not Path(lms_exe).is_file():
        return None
    try:
        completed = _subprocess.run(
            [lms_exe, "ls", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (_subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if completed.returncode != 0:
        return None
    try:
        listing = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(listing, list):
        return None
    # LM Studio surfaces three identifiers per model; any can match the
    # `serving_model_name` we received: `modelKey` (short id, e.g.
    # `qwen3.5-4b-mlx`), `indexedModelIdentifier` (namespaced, e.g.
    # `mlx-community/Qwen3.5-4B-MLX-4bit`), or the relative `path`
    # (same as indexed id for most models). Accept any of the three.
    for entry in listing:
        if not isinstance(entry, dict):
            continue
        candidates = {
            str(entry.get(field) or "").strip()
            for field in ("modelKey", "indexedModelIdentifier", "path")
        }
        if model_key not in candidates:
            continue
        rel_path = str(entry.get("path") or "").strip()
        if not rel_path:
            continue
        models_root = Path.home() / ".lmstudio" / "models"
        absolute = models_root / rel_path
        # Never resolve a base model to one of the platform's own published
        # fine-tunes (placed under <models_root>/<exclude_namespace>/).
        if _is_under_namespace(absolute, models_root, exclude_namespace):
            break
        if _is_mlx_model_dir(absolute):
            return str(absolute)
        # lms ls matched model_key but the path field is stale/wrong.
        # Fall through to filesystem scan below.
        break
    else:
        return None  # model_key not found in lms ls listing

    # The lms ls listing matched model_key but the reported path doesn't exist
    # on disk (LM Studio's index can use a different naming convention than the
    # actual directory). Walk ~/.lmstudio/models to find the real location.
    return _scan_lmstudio_models_for_key(
        model_key, exclude_namespace=exclude_namespace
    )


def resolve_trainer_model_name(
    base_model_name: str,
    hyperparams_json: dict[str, Any],
    settings: Settings,
) -> str:
    explicit = str(hyperparams_json.get("trainer_model_name") or "").strip()
    if explicit:
        return explicit
    # If the user picked a base model that LM Studio already has on disk,
    # train on that exact local copy. Avoids silently swapping a 4B
    # picker selection for a 0.5B HF checkpoint via the env map.
    #
    # Exclude the platform's own publish namespace so a retrain of an
    # already-published base never resolves to the previous fine-tune (which
    # lives under <models_dir>/<mlx_model_namespace>/ and fuzzy-matches the
    # base name it was derived from) and trains on top of it.
    local_path = _resolve_lmstudio_model_path(
        base_model_name, exclude_namespace=settings.mlx_model_namespace
    )
    if local_path:
        return local_path
    model_map = _parse_model_map(settings.ft_trainer_model_map_json)
    if base_model_name in model_map:
        return model_map[base_model_name]
    if "/" in base_model_name:
        return base_model_name
    raise RuntimeError(
        "trainer_model_name is required: no LM Studio model matches the base, "
        "no FT_TRAINER_MODEL_MAP_JSON entry, and the base is not a HF model id."
    )


def build_training_config(
    *,
    base_model_name: str,
    training_method: str,
    hyperparams_json: dict[str, Any],
    settings: Settings,
    train_rows: int = 0,
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
    # Auto-scale iterations + LR based on dataset size.
    #
    # Empirically (see ft-job-7d819c3a9721 training.log: 9 rows × 27 iters at
    # LR=2e-4 → train loss 6.5 → 8.8 → 8.0, then degenerate "PDF PDFuser"
    # output) the default 2e-4 LR is far too aggressive for tiny datasets.
    # Lower the LR sharply when the dataset is small so the LoRA adapter
    # doesn't ratchet the model into divergence on the first few passes.
    #
    # The brackets below are conservative: any explicit override in
    # hyperparams_json wins, so power users keep full control.
    _user_iters = hyperparams_json.get("mlx_iters")
    if _user_iters is not None:
        resolved_iters = max(10, int(_user_iters))
    elif train_rows > 0:
        # Target ~3 passes over the data, clamped to [10, 500].
        if train_rows < 20:
            # Tiny datasets: ~6 passes (min 30) so the adapter actually
            # imprints the examples. Earlier this was capped at 2 passes
            # (train_rows * 2) to avoid divergence, but that was a workaround
            # for the old aggressive 2e-4 LR. With the LR now dialed to 1e-5
            # for small N (below), 2 passes barely moves the weights — the FT
            # model learns the domain persona but not the specific facts, so
            # its answers look identical to base. More passes at the low LR
            # sharpen recall without the divergence the high LR caused.
            resolved_iters = max(30, min(120, train_rows * 6))
        else:
            resolved_iters = max(10, min(500, train_rows * 3))
    else:
        resolved_iters = max(10, int(settings.ft_mlx_iters))

    # Resolve learning rate: user override wins; otherwise auto-scale by N.
    if "learning_rate" in hyperparams_json:
        resolved_lr = float(hyperparams_json["learning_rate"])
    elif train_rows and train_rows < 15:
        resolved_lr = 1e-5  # 9 rows → divergence at 2e-4; drop 20×
    elif train_rows and train_rows < 30:
        resolved_lr = 3e-5
    elif train_rows and train_rows < 100:
        resolved_lr = 8e-5
    else:
        resolved_lr = 2e-4  # original default for healthy-sized datasets

    return TrainingConfig(
        trainer_model_name=resolve_trainer_model_name(
            base_model_name, hyperparams_json, settings
        ),
        base_model_name=base_model_name,
        training_method=normalized_method,
        trainer_backend=trainer_backend,
        epochs=float(hyperparams_json.get("epochs", 1)),
        learning_rate=resolved_lr,
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
        mlx_iters=resolved_iters,
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
        train_rows=export_result.row_counts.get("train", 0),
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


_LOSS_LINE_RE = re.compile(
    r"Iter\s+\d+\s*:\s*Train loss\s+([0-9]+\.[0-9]+)", re.IGNORECASE
)


def _parse_loss_history(logs_path: Path) -> list[float]:
    """Extract per-iter train losses from an mlx_lm.lora training log."""
    try:
        text = logs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    losses: list[float] = []
    for match in _LOSS_LINE_RE.finditer(text):
        try:
            losses.append(float(match.group(1)))
        except ValueError:
            continue
    return losses


def _detect_loss_divergence(losses: list[float]) -> str | None:
    """Return a short description if `losses` looks diverged, else None.

    Two signals catch the modes we've actually seen:

    * Last loss is materially worse than the *first* recorded loss
      (e.g. 6.5 → 8.0 in the ft-job-7d819c3a9721 incident).  We require
      at least three samples so a one-step blip doesn't trip the check.
    * Last loss is non-finite / NaN.

    Both checks are intentionally conservative: a healthy run usually
    shows the loss dropping ≥10% from its starting value, so the
    threshold here (first × 1.10) only fires on real regressions.
    """
    if not losses:
        return None
    last = losses[-1]
    if not math.isfinite(last):
        return f"final loss is non-finite ({last!r})"
    if len(losses) < 3:
        return None
    first = losses[0]
    if first <= 0:
        return None
    # Allow up to 10% increase before flagging as divergence — anything
    # beyond that means the LoRA actively made the model worse.
    if last > first * 1.10:
        return (
            f"loss rose from {first:.3f} (iter 1) to {last:.3f} "
            f"(final), Δ={last - first:+.3f}"
        )
    return None


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

    # Post-training divergence check: parse the per-iter losses mlx_lm.lora
    # printed and refuse to fuse + publish a model whose loss obviously did
    # not converge.  Without this, a misconfigured run silently produces a
    # broken adapter that only fails at /inference/verify time (see the
    # ft-job-7d819c3a9721 incident: loss 6.5 → 8.8 → 8.0 was accepted and
    # the fused model degenerated to "PDF PDFuser" output).
    loss_history = _parse_loss_history(logs_path)
    divergence = _detect_loss_divergence(loss_history)
    if divergence is not None:
        with logs_path.open("a", encoding="utf-8") as log_fh:
            log_fh.write(f"\nDIVERGENCE DETECTED: {divergence}\n")
        raise RuntimeError(
            "MLX QLoRA training appears to have diverged "
            f"({divergence}). Loss history: {loss_history}. "
            "Common fixes: lower learning_rate, reduce iters, "
            "or train on a larger dataset."
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
