from __future__ import annotations

from e2e_helpers import (
    E2ESkip,
    assert_non_empty_string,
    ensure,
    find_artifact_only_model,
    get_selectable_model,
    json_dict,
    print_ok,
    print_step,
    request,
    request_json,
    run_main,
    wait_for_api_health,
)


def main() -> None:
    wait_for_api_health()
    selected_model = get_selectable_model()
    selected_model_id = assert_non_empty_string(selected_model.get("id"), "selected model id")
    serving_model_name = str(selected_model.get("serving_model_name") or "").strip()

    print_step(f"Running inference with model_id={selected_model_id}")
    payload = request_json(
        "POST",
        "/inference/run",
        json_body={
            "model_id": selected_model_id,
            "prompt": "Summarize this demo platform in one sentence.",
        },
        expected_status=200,
    )
    payload = json_dict(payload, "Inference response")
    assert_non_empty_string(payload.get("answer"), "inference answer")

    model_payload = json_dict(payload.get("model"), "Inference model payload")
    ensure(model_payload.get("id") == selected_model_id, "Inference response model id did not match selected model")

    meta = json_dict(payload.get("meta"), "Inference meta payload")
    if serving_model_name and meta.get("used_fallback") is False:
        ensure(
            str(meta.get("model") or "").strip() == serving_model_name,
            "Inference meta.model did not match the selected serving model",
        )

    artifact_only_model = find_artifact_only_model()
    if artifact_only_model is not None:
        artifact_model_id = assert_non_empty_string(artifact_only_model.get("id"), "artifact-only model id")
        print_step(f"Verifying artifact-only model rejection for model_id={artifact_model_id}")
        blocked = request(
            "POST",
            "/inference/run",
            json_body={
                "model_id": artifact_model_id,
                "prompt": "This should be rejected because the model is artifact-only.",
            },
            expected_status={400, 404},
        )
        ensure(
            any(token in blocked.text.lower() for token in ("model", "artifact", "serving", "publish")),
            "Artifact-only inference rejection did not explain the gating reason",
        )
        print_ok("Artifact-only model was rejected for inference")
    else:
        raise E2ESkip("No artifact-only fine-tuned model exists yet; skipping artifact-only inference rejection subcase")

    print_ok("Real Ollama inference smoke passed")


if __name__ == "__main__":
    run_main(main)
