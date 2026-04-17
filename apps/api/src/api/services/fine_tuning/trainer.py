from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, cast

from api.config import Settings
from api.services.fine_tuning.dataset_formatters import DatasetExportResult


SUPPORTED_REAL_TRAINING_METHODS = {"sft_lora"}


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
    return TrainingConfig(
        trainer_model_name=resolve_trainer_model_name(
            base_model_name, hyperparams_json, settings
        ),
        base_model_name=base_model_name,
        training_method=normalized_method,
        trainer_backend=settings.ft_trainer_backend,
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
    )


def _detect_device(settings: Settings) -> str:
    try:
        import torch
    except Exception as exc:  # pragma: no cover - import error validated by caller
        raise RuntimeError(
            "torch is required for real fine-tuning. Install training dependencies first."
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
            "real fine-tuning dependencies are missing: " + ", ".join(sorted(missing))
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
    if config.trainer_backend != "local_peft":
        raise RuntimeError(f"unsupported trainer backend: {config.trainer_backend}")
    _require_training_dependencies()
    return _run_local_peft_training(
        export_result, config=config, settings=settings, output_dir=output_dir
    )


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
        use_cpu=device == "cpu",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        eval_dataset=tokenized_val,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
        processing_class=tokenizer,
    )
    train_output = trainer.train()

    adapter_dir.mkdir(parents=True, exist_ok=True)
    model_for_save = cast(Any, trainer.model)
    assert model_for_save is not None
    model_for_save.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))

    metrics: dict[str, Any] = dict(train_output.metrics)
    evaluation: dict[str, Any] = {
        "status": "not_run" if tokenized_val is None else "available",
        "baseline_comparison": "not_implemented",
    }
    if tokenized_val is not None:
        evaluation_metrics = trainer.evaluate()
        evaluation = {
            "status": "completed",
            "baseline_comparison": "not_implemented",
            "metrics": evaluation_metrics,
        }
        metrics["evaluation"] = evaluation_metrics

    merged_output_path: str | None = None
    if config.export_merged_model:
        merge_source = cast(Any, trainer.model)
        assert merge_source is not None
        merged_model = merge_source.merge_and_unload()
        merged_model_dir.mkdir(parents=True, exist_ok=True)
        merged_model.save_pretrained(str(merged_model_dir))
        tokenizer.save_pretrained(str(merged_model_dir))
        merged_output_path = str(merged_model_dir)

    report_payload = {
        "config": asdict(config),
        "device": device,
        "export": export_result.format_summary,
        "metrics": metrics,
        "evaluation": evaluation,
        "artifacts": {
            "adapter_dir": str(adapter_dir),
            "merged_model_dir": merged_output_path,
        },
    }
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    logs.append(json.dumps(metrics, ensure_ascii=False))
    logs_path.write_text("\n".join(logs) + "\n", encoding="utf-8")

    return TrainingArtifacts(
        adapter_dir=str(adapter_dir),
        report_path=str(report_path),
        merged_model_dir=merged_output_path,
        logs_path=str(logs_path),
        metrics=metrics,
        evaluation=evaluation,
        trainer_backend=config.trainer_backend,
        trainer_model_name=config.trainer_model_name,
        device=device,
    )
