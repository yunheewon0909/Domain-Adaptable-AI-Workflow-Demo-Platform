from __future__ import annotations

from e2e_helpers import (
    assert_non_empty_string,
    choose_workflow_key,
    create_locked_ft_dataset,
    default_ft_rows,
    enqueue_ft_smoke_training,
    ensure,
    find_artifact_only_model,
    json_dict,
    list_models,
    print_ok,
    print_step,
    request,
    run_main,
    timestamp_suffix,
    wait_for_api_health,
    wait_for_ft_training_job,
)


def _ensure_artifact_only_model() -> dict[str, object]:
    existing = find_artifact_only_model()
    if existing is not None:
        return existing

    dataset_info = create_locked_ft_dataset(
        dataset_name=f"E2E Model Gating {timestamp_suffix()}",
        rows=default_ft_rows(),
    )
    enqueue = enqueue_ft_smoke_training(dataset_info["version_id"])
    enqueue = json_dict(enqueue, "FT training enqueue response")
    training = wait_for_ft_training_job(assert_non_empty_string(enqueue.get("id"), "training job id"), timeout_seconds=300)
    ensure(training.get("status") == "succeeded", f"Model-gating FT prerequisite failed: {training}")
    model = find_artifact_only_model()
    ensure(model is not None, "Could not locate an artifact-only model after FT smoke training")
    if model is None:
        raise AssertionError("unreachable")
    return model


def main() -> None:
    wait_for_api_health()
    workflow_key = choose_workflow_key()
    artifact_only_model = _ensure_artifact_only_model()
    model_id = assert_non_empty_string(artifact_only_model.get("id"), "artifact-only model id")

    readiness = json_dict(artifact_only_model.get("readiness"), "Artifact-only model readiness")
    ensure(artifact_only_model.get("source_type") == "fine_tuned", "Expected a fine_tuned artifact-only model")
    ensure(artifact_only_model.get("status") == "artifact_ready", "Expected artifact_ready model status")
    ensure(readiness.get("selectable") is False, "Artifact-only model should not be selectable")

    print_step("Verifying /inference/run rejects artifact-only model_id")
    inference = request(
        "POST",
        "/inference/run",
        json_body={"prompt": "reject artifact-only model", "model_id": model_id},
        expected_status={400, 404},
    )
    ensure(any(token in inference.text.lower() for token in ("artifact", "serving", "model", "publish")), "Inference rejection did not explain readiness gating")

    print_step("Verifying workflow enqueue rejects artifact-only model_id")
    workflow = request(
        "POST",
        f"/workflows/{workflow_key}/jobs",
        json_body={
            "dataset_key": "industrial_demo",
            "prompt": "reject artifact-only model",
            "k": 4,
            "model_id": model_id,
        },
        expected_status={400, 404},
    )
    ensure(any(token in workflow.text.lower() for token in ("artifact", "serving", "model", "publish")), "Workflow rejection did not explain readiness gating")

    models = list_models()
    selectable_ids = {
        str(item.get("id"))
        for item in models
        if isinstance(item.get("readiness"), dict) and json_dict(item.get("readiness"), "Model readiness").get("selectable") is True
    }
    ensure(model_id not in selectable_ids, "Artifact-only model unexpectedly appeared in selectable model list")
    print_ok("Artifact-only model gating smoke passed")


if __name__ == "__main__":
    run_main(main)
