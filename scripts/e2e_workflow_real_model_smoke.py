from __future__ import annotations

from e2e_helpers import (
    assert_non_empty_string,
    choose_workflow_key,
    ensure,
    get_selectable_model,
    json_dict,
    json_list,
    print_ok,
    print_step,
    request,
    request_json,
    run_main,
    wait_for_api_health,
    wait_for_job,
)


def _result_has_non_empty_content(result_json: dict[str, object]) -> bool:
    for key in ("summary", "rationale", "executive_summary", "title"):
        value = result_json.get(key)
        if isinstance(value, str) and value.strip():
            return True
    for key in ("key_points", "recommendations", "findings", "actions"):
        value = result_json.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def main() -> None:
    wait_for_api_health()
    selected_model = get_selectable_model()
    model_id = assert_non_empty_string(selected_model.get("id"), "selected model id")
    workflow_key = choose_workflow_key()

    print_step(f"Enqueueing workflow={workflow_key} with dataset_key=industrial_demo and model_id={model_id}")
    enqueue = request_json(
        "POST",
        f"/workflows/{workflow_key}/jobs",
        json_body={
            "dataset_key": "industrial_demo",
            "prompt": "요약해",
            "k": 4,
            "model_id": model_id,
        },
        expected_status=202,
    )
    enqueue = json_dict(enqueue, "Workflow enqueue response")
    job_id = assert_non_empty_string(enqueue.get("job_id"), "workflow job id")

    job = wait_for_job(job_id, timeout_seconds=180)
    ensure(job.get("status") == "succeeded", f"Workflow job did not succeed: {job}")
    error_text = str(job.get("error") or "")
    ensure("nvidia" not in error_text.lower(), "Workflow job error leaked noisy nvidia install output")
    ensure("uv pip" not in error_text.lower(), "Workflow job error leaked noisy uv install output")

    result_json = json_dict(job.get("result_json"), "Workflow job result_json")
    meta = json_dict(result_json.get("meta"), "Workflow result meta")
    ensure(meta.get("model_id") == model_id, "Workflow meta.model_id did not match selected model")
    ensure(bool(meta.get("selected_model")), "Workflow meta.selected_model was empty")

    rag_status = str(meta.get("rag_status") or "").strip()
    if rag_status == "not_ready":
        warnings = json_list(meta.get("warnings"), "Workflow warnings")
        ensure(len(warnings) > 0, "RAG-not-ready result must include structured warnings")
        ensure(
            any("RAG index is not ready" in str(item) for item in warnings),
            "RAG-not-ready workflow result did not include the expected readiness warning",
        )
        print_ok("Workflow returned structured rag.db-not-ready guidance instead of a fatal subprocess failure")
    else:
        ensure(_result_has_non_empty_content(result_json), "Workflow result did not contain a non-empty answer payload")
        evidence = json_list(result_json.get("evidence"), "Workflow evidence")
        ensure(len(evidence) > 0, "Workflow success result must include evidence")
        print_ok("Workflow returned a non-empty result with evidence")

    print_step("Verifying invalid model_id rejection")
    invalid = request(
        "POST",
        f"/workflows/{workflow_key}/jobs",
        json_body={
            "dataset_key": "industrial_demo",
            "prompt": "invalid model check",
            "k": 4,
            "model_id": "model-does-not-exist",
        },
        expected_status={400, 404},
    )
    ensure("model" in invalid.text.lower(), "Invalid model_id rejection did not mention model lookup")
    print_ok("Invalid workflow model_id was rejected")
    print_ok("Workflow real-model smoke passed")


if __name__ == "__main__":
    run_main(main)
