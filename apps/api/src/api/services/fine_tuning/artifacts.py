from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from api.config import Settings
from api.services.fine_tuning.dataset_formatters import DatasetExportResult
from api.services.fine_tuning.trainer import TrainingArtifacts


def build_publish_manifest(
    *,
    manifest_dir: Path,
    dataset_export: DatasetExportResult,
    training_artifacts: TrainingArtifacts,
    base_model_name: str,
    trainer_model_name: str,
    settings: Settings,
) -> tuple[Path, dict[str, Any]]:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    modelfile_path = manifest_dir / "Modelfile.template"
    model_name = None
    if settings.ollama_model_namespace:
        model_name = f"{settings.ollama_model_namespace}/{Path(training_artifacts.adapter_dir).parent.name}"

    modelfile_contents = "\n".join(
        [
            f"# Publish seam generated for {dataset_export.dataset_version_id}",
            f"# Serving base lineage: {base_model_name}",
            f"# Trainer base source: {trainer_model_name}",
            "# This template is reviewer-facing only until an Ollama-compatible artifact is produced.",
            f"# Adapter directory: {training_artifacts.adapter_dir}",
            f"# Merged model directory: {training_artifacts.merged_model_dir or 'not exported'}",
            "",
            "# Example future directions:",
            "# - convert a merged model to an Ollama-compatible format",
            "# - replace this template with a validated Modelfile or import manifest",
        ]
    )
    modelfile_path.write_text(modelfile_contents + "\n", encoding="utf-8")

    payload = {
        "status": "publish_ready",
        "publish_target": "ollama",
        "ollama_publish_enabled": settings.ollama_publish_enabled,
        "candidate_model_name": model_name,
        "dataset_version_id": dataset_export.dataset_version_id,
        "base_model_name": base_model_name,
        "trainer_model_name": trainer_model_name,
        "adapter_dir": training_artifacts.adapter_dir,
        "merged_model_dir": training_artifacts.merged_model_dir,
        "modelfile_template_path": str(modelfile_path),
        "notes": [
            "Training completed and artifacts are ready for a future serving/import step.",
            "This repo does not claim direct fine-tuning inside Ollama.",
        ],
    }
    manifest_path = manifest_dir / "publish_manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path, payload
