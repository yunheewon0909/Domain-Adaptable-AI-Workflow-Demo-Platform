from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, cast

from api.config import Settings
from api.services.fine_tuning.dataset_formatters import DatasetExportResult


SUPPORTED_REAL_TRAINING_METHODS = {"sft_lora", "sft_qlora"}
SUPPORTED_TRAINER_BACKENDS = {"local_peft", "deterministic_smoke", "mlx_qlora"}
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
    # Determine backend: MLX for sft_qlora, local_peft for sft_lora, or explicit
    if normalized_method == "sft_qlora":
        inferred_backend = "mlx_qlora"
    else:
        inferred_backend = settings.ft_trainer_backend.strip() or "local_peft"
    trainer_backend = inferred_backend
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


# ---- Device detection (kept for local_peft compatibility) -------------


def _detect_device(settings: Settings) -> str:
    try:
        import torch
    except Exception as exc:
        raise RuntimeError(
            "torch is required for local_peft (non-MLX) training."
        ) from exc

    requested = settings.training_device
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("TRAINING_DEVICE=cuda but CUDA is not available")
        return "cuda"
    if requested == "mps":
        if not torch.backends.mps.is_available():
            raise RuntimeError("TRAINING_DEVICE=mps but MPS is not available")
        return "mps"
    if requested == "cpu":
        if not settings.training_allow_cpu:
            raise RuntimeError(
                "CPU training is disabled by default. Set TRAINING_ALLOW_CPU=true only for tiny smoke-test models."
            )
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    if settings.training_allow_cpu:
        return "cpu"
    raise RuntimeError(
        "No GPU accelerator is available and CPU training is disabled. Set TRAINING_DEVICE explicitly or enable TRAINING_ALLOW_CPU for tiny local smoke tests."
    )


def _require_training_dependencies() -> None:
    missing: list[str] = []
    for package_name in ["torch", "datasets", "transformers", "peft", "accelerate"]:
        try:
            __import__(package_name)
        except Exception:
            missing.append(package_name)
    if missing:
        raise RuntimeError(
            "real fine-tuning dependencies (torch/peft) are missing: "
            + ", ".join(sorted(missing))
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
    if config.trainer_backend == "mlx_qlora":
        return _run_mlx_qlora_training(
            export_result, config=config, settings=settings, output_dir=output_dir
        )
    if config.trainer_backend != "local_peft":
        raise RuntimeError(f"unsupported trainer backend: {config.trainer_backend}")
    try:
        _require_training_dependencies()
        return _run_local_peft_training(
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
                lineage_backend="local_peft+smoke_fallback",
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
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "r": config.lora_r,
        "lora_alpha": config.lora_alpha,
        "lora_dropout": config.lora_dropout,
        "bias": "none",
        "target_modules": ["q_proj", "v_proj"],
        "inference_mode": True,
        "smoke_fallback": True,
    }
    (adapter_dir / "adapter_config.json").write_text(
        json.dumps(adapter_config, indent=2), encoding="utf-8"
    )
    (adapter_dir / "adapter_model.safetensors").write_bytes(
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
            "runtime_note": "Use host MLX backend for real trainer validation",
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
        "Use host MLX backend for real trainer validation",
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


def _run_mlx_qlora_training(
    export_result: DatasetExportResult,
    *,
    config: TrainingConfig,
    settings: Settings,
    output_dir: Path,
) -> TrainingArtifacts:
    """Run MLX QLoRA training via subprocess (mlx_lm.lora + mlx_lm.fuse)."""
    import shutil
    import subprocess
    import time

    output_dir.mkdir(parents=True, exist_ok=True)
    adapter_dir = output_dir / "adapters"
    fused_dir = output_dir / "fused_model"
    logs_path = output_dir / "training.log"
    report_path = output_dir / "training_report.json"

    # Build MLX training data dir (train.jsonl + valid.jsonl from export)
    mlx_data_dir = output_dir / "mlx_data"
    mlx_data_dir.mkdir(parents=True, exist_ok=True)

    if export_result.train_file:
        (mlx_data_dir / "train.jsonl").write_bytes(
            Path(export_result.train_file).read_bytes()
        )
    if export_result.val_file:
        (mlx_data_dir / "valid.jsonl").write_bytes(
            Path(export_result.val_file).read_bytes()
        )

    logs: list[str] = [
        f"trainer_backend=mlx_qlora",
        f"base_model={config.base_model_name}",
        f"trainer_model={config.trainer_model_name}",
        f"iters={config.mlx_iters}",
        f"batch_size={config.batch_size}",
        f"lora_layers={config.mlx_lora_layers}",
        f"lora_r={config.lora_r}",
        f"learning_rate={config.learning_rate}",
    ]

    # Step 1: MLX LoRA training
    lora_exe = shutil.which("mlx_lm.lora")
    if not lora_exe:
        raise RuntimeError("mlx_lm.lora CLI is required. Install with: brew install mlx-lm")
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
    logs.append(f"lora_cmd={' '.join(str(a) for a in lora_cmd)}")
    print(f"[MLX QLoRA] Starting training: {' '.join(str(a) for a in lora_cmd)}")

    start = time.monotonic()
    result = subprocess.run(lora_cmd, capture_output=True, text=True)
    elapsed = time.monotonic() - start

    logs.append(f"training_elapsed_s={elapsed:.1f}")
    logs.append(f"training_returncode={result.returncode}")
    if result.stdout:
        logs.append(f"lora_stdout={result.stdout.strip()[-1000:]}")
    if result.stderr:
        logs.append(f"lora_stderr={result.stderr.strip()[-1000:]}")

    if result.returncode != 0:
        logs_path.write_text("\n".join(logs) + "\n", encoding="utf-8")
        raise RuntimeError(
            f"MLX QLoRA training failed (exit={result.returncode}): "
            f"{result.stderr.strip()[-500:]}"
        )

    # Check for adapter output
    adapter_weights = adapter_dir / "adapters.safetensors"
    if not adapter_weights.exists():
        # mlx-lm 0.20+ may use npz format
        adapter_weights = adapter_dir / "adapters.npz"
    if not adapter_weights.exists():
        logs_path.write_text("\n".join(logs) + "\n", encoding="utf-8")
        raise RuntimeError(
            f"MLX QLoRA training completed but adapter not found at {adapter_dir}/*"
        )

    # Step 2: Fuse adapter into base model
    logs.append(f"fusing model to {fused_dir}")
    fuse_exe = shutil.which("mlx_lm.fuse")
    if not fuse_exe:
        raise RuntimeError("mlx_lm.fuse CLI is required. Install with: brew install mlx-lm")
    fuse_cmd = [
        fuse_exe,
        "--model", config.trainer_model_name,
        "--adapter-path", str(adapter_dir),
        "--save-path", str(fused_dir),
    ]
    print(f"[MLX QLoRA] Fusing model: {' '.join(fuse_cmd)}")
    fuse_result = subprocess.run(fuse_cmd, capture_output=True, text=True)
    if fuse_result.returncode != 0:
        logs.append(f"fuse_stderr={fuse_result.stderr.strip()[-500:]}")
        logs_path.write_text("\n".join(logs) + "\n", encoding="utf-8")
        raise RuntimeError(
            f"MLX model fusion failed (exit={fuse_result.returncode}): "
            f"{fuse_result.stderr.strip()[-500:]}"
        )
    logs.append("fusion succeeded")

    # Write logs
    logs_path.write_text("\n".join(logs) + "\n", encoding="utf-8")

    # Build report
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


# ---- Local PEFT backend (kept for backward compat) --------------------


def _run_local_peft_training(
    export_result: DatasetExportResult,
    *,
    config: TrainingConfig,
    settings: Settings,
    output_dir: Path,
) -> TrainingArtifacts:
    import torch
    from datasets import load_dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    device = _detect_device(settings)
    output_dir.mkdir(parents=True, exist_ok=True)
    adapter_dir = output_dir / "adapter"
    logs_path = output_dir / "training.log"
    report_path = output_dir / "training_report.json"
    merged_model_dir = output_dir / "merged_model"

    set_seed(config.seed)
    logs: list[str] = [
        f"trainer_backend={config.trainer_backend}",
        f"trainer_model_name={config.trainer_model_name}",
        f"device={device}",
        f"training_method={config.training_method}",
    ]

    tokenizer = AutoTokenizer.from_pretrained(config.trainer_model_name)
    if tokenizer.pad_token is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token

    torch_dtype = None
    if device == "cuda" and torch.cuda.is_bf16_supported():
        torch_dtype = torch.bfloat16

    model = AutoModelForCausalLM.from_pretrained(
        config.trainer_model_name,
        torch_dtype=torch_dtype,
    )
    if tokenizer.pad_token_id is not None:
        model.config.pad_token_id = tokenizer.pad_token_id

    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
    )
    model = get_peft_model(model, lora_config)

    data_files: dict[str, str] = {}
    if export_result.train_file:
        data_files["train"] = export_result.train_file
    if export_result.val_file:
        data_files["validation"] = export_result.val_file
    dataset_dict = load_dataset("json", data_files=data_files)

    def _tokenize(batch: dict[str, list[Any]]) -> dict[str, Any]:
        texts = [str(item) for item in batch.get("text", [])]
        encoded = tokenizer(
            texts,
            truncation=True,
            max_length=config.max_seq_length,
            padding=False,
        )
        encoded["labels"] = [list(item) for item in encoded["input_ids"]]
        return encoded

    tokenized_train = dataset_dict["train"].map(
        _tokenize,
        batched=True,
        remove_columns=dataset_dict["train"].column_names,
    )
    tokenized_val = None
    if "validation" in dataset_dict:
        tokenized_val = dataset_dict["validation"].map(
            _tokenize,
            batched=True,
            remove_columns=dataset_dict["validation"].column_names,
        )

    training_args = TrainingArguments(
        output_dir=str(output_dir / "trainer_state"),
        overwrite_output_dir=True,
        num_train_epochs=config.epochs,
        learning_rate=config.learning_rate,
        per_device_train_batch_size=config.batch_size,
        per_device_eval_batch_size=config.per_device_eval_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        eval_strategy=(
            config.eval_strategy
            if tokenized_val is not None and config.eval_strategy != "no"
            else "no"
        ),
        save_strategy="no",
        logging_strategy="epoch",
        report_to=[],
        seed=config.seed,
        max_steps=config.max_steps,
        fp16=device == "cuda" and not torch.cuda.is_bf16_supported(),
        bf16=device == "cuda" and torch.cuda.is_bf16_supported(),
    )

    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer, mlm=False
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_val,
        data_collator=data_collator,
    )

    train_result = trainer.train()
    logs.append(f"train_runtime_s={round(train_result.metrics.get('train_runtime', 0), 1)}")
    logs.append(f"train_loss={round(train_result.metrics.get('train_loss', 0), 4)}")
    trainer.save_model(str(adapter_dir))
    logs.append(f"adapter saved to {adapter_dir}")

    if config.export_merged_model:
        merged_model_dir.mkdir(parents=True, exist_ok=True)
        model = model.merge_and_unload()
        model.save_pretrained(str(merged_model_dir))
        tokenizer.save_pretrained(str(merged_model_dir))
        logs.append(f"merged model saved to {merged_model_dir}")
    else:
        merged_model_dir = None

    if tokenized_val is not None and config.eval_strategy != "no":
        eval_metrics = trainer.evaluate()
        eval_dict = dict(eval_metrics)
    else:
        eval_dict = {"status": "skipped"}

    logs_path.write_text("\n".join(logs) + "\n", encoding="utf-8")

    report_payload = {
        "config": {
            **asdict(config),
            "trainer_backend": config.trainer_backend,
        },
        "device": device,
        "export": export_result.format_summary,
        "metrics": dict(train_result.metrics),
        "evaluation": eval_dict,
        "artifacts": {
            "adapter_dir": str(adapter_dir),
            "merged_model_dir": str(merged_model_dir) if merged_model_dir else None,
        },
    }
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return TrainingArtifacts(
        adapter_dir=str(adapter_dir),
        report_path=str(report_path),
        merged_model_dir=str(merged_model_dir) if merged_model_dir else None,
        logs_path=str(logs_path),
        metrics=dict(train_result.metrics),
        evaluation=eval_dict,
        trainer_backend=config.trainer_backend,
        trainer_model_name=config.trainer_model_name,
        device=device,
    )
