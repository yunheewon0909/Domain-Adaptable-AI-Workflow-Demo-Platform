from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from api.config import Settings
from api.services.fine_tuning.dataset_formatters import DatasetExportResult
from api.services.fine_tuning.trainer import TrainingArtifacts


ADAPTER_WEIGHT_FILENAMES = (
    "adapters.safetensors",
    "adapters.npz",
    # Legacy names are accepted so older artifacts remain inspectable.
    "adapter_model.safetensors",
    "adapter_model.bin",
)


def _path_metadata(path: Path) -> dict[str, Any]:
    exists = path.exists()
    is_dir = path.is_dir() if exists else False
    is_file = path.is_file() if exists else False
    size_bytes = path.stat().st_size if is_file else None
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": is_dir,
        "is_file": is_file,
        "size_bytes": size_bytes,
    }


def _non_empty_file(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def validate_training_artifacts(
    *,
    training_artifacts: TrainingArtifacts,
    base_model_name: str,
    smoke_test: bool = False,
) -> dict[str, Any]:
    adapter_dir = Path(training_artifacts.adapter_dir)
    adapter_config_path = adapter_dir / "adapter_config.json"
    adapter_weight_path = next(
        (
            adapter_dir / name
            for name in ADAPTER_WEIGHT_FILENAMES
            if (adapter_dir / name).exists()
        ),
        adapter_dir / ADAPTER_WEIGHT_FILENAMES[0],
    )
    report_path = Path(training_artifacts.report_path)
    logs_path = Path(training_artifacts.logs_path)
    merged_model_dir = (
        Path(training_artifacts.merged_model_dir)
        if training_artifacts.merged_model_dir is not None
        else None
    )

    checks = {
        "adapter_dir": _path_metadata(adapter_dir),
        "adapter_config": _path_metadata(adapter_config_path),
        "adapter_model": _path_metadata(adapter_weight_path),
        "training_report": _path_metadata(report_path),
        "training_log": _path_metadata(logs_path),
    }
    if merged_model_dir is not None:
        checks["merged_model_dir"] = _path_metadata(merged_model_dir)

    missing: list[str] = []
    if not adapter_dir.exists() or not adapter_dir.is_dir():
        missing.append("adapter directory")
    if not _non_empty_file(adapter_config_path):
        missing.append("adapter_config.json")
    if not _non_empty_file(adapter_weight_path):
        missing.append("adapter model weights")
    if not _non_empty_file(report_path):
        missing.append("training_report.json")
    if not _non_empty_file(logs_path):
        missing.append("training.log")

    warnings: list[str] = []
    smoke_fallback_used = bool(training_artifacts.metrics.get("smoke_fallback_used"))
    if training_artifacts.trainer_model_name != base_model_name:
        warnings.append(
            "Serving lineage and trainer source differ. This is acceptable for smoke tests but does not mean the serving model itself was fine-tuned."
        )
    if merged_model_dir is None:
        warnings.append(
            "No merged serving model was exported. The local output is an adapter artifact, not a serving model."
        )
    if smoke_fallback_used:
        warnings.extend(
            [
                "Smoke fallback trainer was used.",
                "This validates dataset/export/artifact/registry flow, not model quality.",
                "Use the Mac-native MLX QLoRA path for real trainer validation.",
            ]
        )

    if smoke_fallback_used or training_artifacts.trainer_backend == "deterministic_smoke":
        artifact_format = "deterministic_smoke_adapter"
    elif training_artifacts.trainer_backend == "mlx_qlora":
        artifact_format = "mlx_lora_adapter"
    else:
        artifact_format = "adapter"

    return {
        "artifact_valid": not missing,
        "artifact_format": artifact_format,
        "base_model_name": base_model_name,
        "trainer_model_name": training_artifacts.trainer_model_name,
        "trainer_backend": training_artifacts.trainer_backend,
        "device": training_artifacts.device,
        "smoke_test": smoke_test,
        "smoke_fallback_used": smoke_fallback_used,
        "missing": missing,
        "warnings": warnings,
        "checks": checks,
    }


def validate_publish_artifacts(
    *,
    manifest_path: Path,
    modelfile_template_path: Path,
    manifest_payload: dict[str, Any],
    training_validation: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "publish_manifest": _path_metadata(manifest_path),
        "modelfile_template": _path_metadata(modelfile_template_path),
    }
    missing: list[str] = []
    if not _non_empty_file(manifest_path):
        missing.append("publish_manifest.json")
    if not _non_empty_file(modelfile_template_path):
        missing.append("Modelfile.template")

    warnings = list(training_validation.get("warnings") or [])
    warnings.append(
        "Publish-ready artifacts exist, but automatic LM Studio import is not implemented by this repository."
    )
    if not str(manifest_payload.get("candidate_model_name") or "").strip():
        warnings.append(
            "No candidate serving model name was derived from the current namespace/job settings."
        )

    return {
        "artifact_valid": training_validation.get("artifact_valid", False)
        and not missing,
        "missing": missing,
        "warnings": warnings,
        "checks": checks,
        "candidate_model_name": manifest_payload.get("candidate_model_name"),
        "runtime_ready": False,
        "runtime_ready_reason": "A publish manifest/template exists, but no real LM Studio serving model has been loaded yet.",
    }


def build_publish_manifest(
    *,
    manifest_dir: Path,
    dataset_export: DatasetExportResult,
    training_artifacts: TrainingArtifacts,
    base_model_name: str,
    trainer_model_name: str,
    settings: Settings,
    dataset_name: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    modelfile_path = manifest_dir / "Modelfile.template"
    # LM Studio scans `~/.lmstudio/models/<creator>/<repo>/` but exposes
    # the model in `/v1/models` under just `<repo>` (the basename) — its
    # default identifier matches the leaf dir name, not the full
    # namespaced path. Use the basename here so the publish probe's
    # `candidate_model_name` matches what LM Studio actually reports.
    # The namespace is still used to lay out the on-disk hierarchy in
    # `register_fused_model`.
    model_name = None
    if settings.mlx_model_namespace:
        if dataset_name:
            safe = re.sub(r"[^a-zA-Z0-9._-]", "_", dataset_name).strip("_")
            model_name = safe or manifest_dir.parent.name
        else:
            model_name = manifest_dir.parent.name

    modelfile_contents = "\n".join(
        [
            f"# Publish seam generated for {dataset_export.dataset_version_id}",
            f"# Serving base lineage: {base_model_name}",
            f"# Trainer base source: {trainer_model_name}",
            "# This template is reviewer-facing only until an LM Studio serving artifact is loaded.",
            f"# Adapter directory: {training_artifacts.adapter_dir}",
            f"# Merged model directory: {training_artifacts.merged_model_dir or 'not exported'}",
            "",
            "# Example future directions:",
            "# - load the merged MLX model into LM Studio",
            "# - replace this template with a validated Modelfile or import manifest",
        ]
    )
    modelfile_path.write_text(modelfile_contents + "\n", encoding="utf-8")

    payload = {
        "status": "publish_ready",
        "publish_target": "lm_studio",
        "lmstudio_publish_enabled": settings.adapter_publish_enabled,
        "automatic_lmstudio_import": False,
        "candidate_model_name": model_name,
        "dataset_version_id": dataset_export.dataset_version_id,
        "base_model_name": base_model_name,
        "trainer_model_name": trainer_model_name,
        "adapter_dir": training_artifacts.adapter_dir,
        "merged_model_dir": training_artifacts.merged_model_dir,
        "modelfile_template_path": str(modelfile_path),
        "notes": [
            "Training completed and artifacts are ready for a future serving/import step.",
            "This repo does not claim direct fine-tuning inside LM Studio.",
            "Automatic LM Studio load/import is not implemented; manual model loading is still required before inference can use a fine-tuned serving model.",
        ],
    }
    manifest_path = manifest_dir / "publish_manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path, payload
