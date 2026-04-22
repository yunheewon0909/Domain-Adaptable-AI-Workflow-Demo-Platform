from __future__ import annotations

from e2e_helpers import (
    artifact_path,
    assert_non_empty_string,
    create_locked_ft_dataset,
    default_ft_rows,
    enqueue_ft_smoke_training,
    ensure,
    json_dict,
    json_list,
    print_ok,
    print_step,
    run_main,
    timestamp_suffix,
    wait_for_api_health,
    wait_for_ft_training_job,
)


def main() -> None:
    wait_for_api_health()
    dataset_info = create_locked_ft_dataset(
        dataset_name=f"E2E FT Smoke Fallback {timestamp_suffix()}",
        rows=default_ft_rows(),
    )
    version_id = dataset_info["version_id"]
    enqueue = enqueue_ft_smoke_training(version_id)
    enqueue = json_dict(enqueue, "FT training enqueue response")
    training_job_id = assert_non_empty_string(enqueue.get("id"), "training job id")
    print_step(f"Polling FT training job {training_job_id}")
    training = wait_for_ft_training_job(training_job_id, timeout_seconds=300)
    ensure(training.get("status") == "succeeded", f"FT smoke job failed: {training}")

    trainer_backend = str(training.get("trainer_backend") or "")
    trainer_model_name = str(training.get("trainer_model_name") or "")
    ensure(
        trainer_backend in {"local_peft+smoke_fallback", "deterministic_smoke", "local_peft"},
        f"Unexpected trainer_backend for FT smoke job: {trainer_backend}",
    )
    artifact_validation = json_dict(training.get("artifact_validation"), "FT training artifact_validation")
    ensure(artifact_validation.get("artifact_valid") is True, "FT artifact_validation.artifact_valid was not true")

    if artifact_validation.get("smoke_fallback_used") is True:
        ensure(
            trainer_model_name == "deterministic-smoke-trainer",
            "Smoke fallback run did not report deterministic-smoke-trainer",
        )
        print_ok("FT smoke fallback path was exercised")
    else:
        print_ok(
            "FT smoke job succeeded without fallback; runtime appears to have completed the local_peft path directly"
        )

    artifact_paths = json_dict(training.get("artifact_paths"), "FT training artifact_paths")
    adapter_dir = artifact_path(artifact_paths.get("adapter_dir"))
    ensure(adapter_dir.is_dir(), f"Adapter dir does not exist: {adapter_dir}")
    ensure((adapter_dir / "adapter_config.json").is_file(), "adapter_config.json was missing")
    ensure(
        (adapter_dir / "adapter_model.safetensors").is_file() or (adapter_dir / "adapter_model.bin").is_file(),
        "adapter weights were missing",
    )
    ensure(artifact_path(artifact_paths.get("training_report_path")).is_file(), "training_report.json was missing")
    ensure(artifact_path(artifact_paths.get("training_log_path")).is_file(), "training.log was missing")
    publish_manifest = artifact_paths.get("publish_manifest_path")
    if publish_manifest:
        ensure(artifact_path(publish_manifest).is_file(), "publish_manifest.json path was reported but missing")

    registered_models = json_list(training.get("registered_models"), "FT registered_models")
    ensure(len(registered_models) > 0, "FT training did not register a model row")
    model = json_dict(registered_models[0], "Registered model payload")
    ensure(model.get("status") == "artifact_ready", "Registered FT model was not artifact_ready")
    ensure(model.get("publish_status") == "publish_ready", "Registered FT model was not publish_ready")
    readiness = json_dict(model.get("readiness"), "Registered model readiness")
    ensure(readiness.get("selectable") is False, "Artifact-only FT model should not be selectable")
    ensure(model.get("serving_model_name") is None, "Artifact-only FT model should not have serving_model_name")
    print_ok("FT smoke fallback/artifact pipeline validation passed")


if __name__ == "__main__":
    run_main(main)
