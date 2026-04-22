from __future__ import annotations

from e2e_helpers import (
    assert_non_empty_string,
    choose_workflow_key,
    create_locked_ft_dataset,
    default_ft_rows,
    enqueue_ft_smoke_training,
    ensure,
    examples_dir,
    get_selectable_model,
    json_dict,
    json_list,
    print_ok,
    print_step,
    request_json,
    request_multipart,
    run_main,
    timestamp_suffix,
    wait_for_api_health,
    wait_for_ft_training_job,
    wait_for_job,
    wait_for_plc_run,
)


def main() -> None:
    wait_for_api_health()
    workflow_key = choose_workflow_key()
    model = get_selectable_model(allow_skip=True)
    model_id = assert_non_empty_string(model.get("id"), "selected model id")

    print_step("Enqueueing two workflow jobs")
    workflow_job_ids: list[str] = []
    for index in range(2):
        enqueue = request_json(
            "POST",
            f"/workflows/{workflow_key}/jobs",
            json_body={
                "dataset_key": "industrial_demo",
                "prompt": f"queue smoke job {index + 1}",
                "k": 4,
                "model_id": model_id,
            },
            expected_status=202,
        )
        enqueue = json_dict(enqueue, "Workflow queue response")
        workflow_job_ids.append(assert_non_empty_string(enqueue.get("job_id"), "workflow job id"))

    print_step("Enqueueing one PLC run")
    csv_path = examples_dir() / "ls-add-demo.csv"
    import_response = json_dict(
        request_multipart(
        "POST",
        "/plc-testcases/import",
        fields={"title": f"E2E Queue PLC {timestamp_suffix()}"},
        files=[("file", csv_path, "text/csv")],
        expected_status=201,
        ).json(),
        "PLC import response",
    )
    suite_id = assert_non_empty_string(import_response.get("suite_id"), "PLC suite id")
    plc_enqueue = request_json(
        "POST",
        "/plc-test-runs",
        json_body={"suite_id": suite_id, "target_key": "stub-local"},
        expected_status=202,
    )
    plc_enqueue = json_dict(plc_enqueue, "PLC queue response")
    plc_run_id = assert_non_empty_string(plc_enqueue.get("job_id"), "PLC run id")

    print_step("Enqueueing one FT smoke job")
    dataset_info = create_locked_ft_dataset(
        dataset_name=f"E2E Queue FT {timestamp_suffix()}",
        rows=default_ft_rows(),
    )
    ft_enqueue = enqueue_ft_smoke_training(dataset_info["version_id"])
    ft_enqueue = json_dict(ft_enqueue, "FT queue response")
    training_job_id = assert_non_empty_string(ft_enqueue.get("id"), "training job id")

    workflow_results = [wait_for_job(job_id, timeout_seconds=180) for job_id in workflow_job_ids]
    plc_result = wait_for_plc_run(plc_run_id, timeout_seconds=180)
    ft_result = wait_for_ft_training_job(training_job_id, timeout_seconds=300)

    ensure(all(item.get("status") in {"succeeded", "failed"} for item in workflow_results), "Workflow queue jobs did not reach terminal states")
    ensure(plc_result.get("status") in {"succeeded", "failed"}, "PLC queue job did not reach a terminal state")
    ensure(ft_result.get("status") in {"succeeded", "failed"}, "FT queue job did not reach a terminal state")

    jobs = json_list(request_json("GET", "/jobs", expected_status=200), "/jobs response")
    relevant_ids = set(workflow_job_ids + [plc_run_id])
    for item in jobs:
        if not isinstance(item, dict):
            continue
        if str(item.get("id")) not in relevant_ids:
            continue
        ensure(item.get("status") not in {"queued", "running"}, "A queued/running job remained after polling completed")

    print_ok("Queue smoke confirmed workflow, PLC, and FT jobs reached terminal states without getting stuck")


if __name__ == "__main__":
    run_main(main)
