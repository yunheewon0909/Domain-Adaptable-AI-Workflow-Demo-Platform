from __future__ import annotations

from e2e_helpers import (
    assert_non_empty_string,
    examples_dir,
    ensure,
    json_dict,
    json_list,
    print_ok,
    print_step,
    request_json,
    request_multipart,
    run_main,
    wait_for_api_health,
    wait_for_plc_run,
)


def main() -> None:
    wait_for_api_health()
    csv_path = examples_dir() / "ls-add-demo.csv"
    ensure(csv_path.is_file(), f"Missing PLC example CSV: {csv_path}")

    print_step("Importing PLC example suite")
    response = request_multipart(
        "POST",
        "/plc-testcases/import",
        fields={"title": "E2E PLC Stub Pipeline"},
        files=[("file", csv_path, "text/csv")],
        expected_status=201,
    )
    imported = json_dict(response.json(), "PLC import response")
    suite_id = assert_non_empty_string(imported.get("suite_id"), "PLC suite id")
    ensure(int(str(imported.get("imported_count") or 0)) > 0, "PLC import did not create any testcase rows")

    suites = json_list(request_json("GET", "/plc-test-suites", expected_status=200), "PLC suite list")
    ensure(any(isinstance(item, dict) and item.get("id") == suite_id for item in suites), "Imported PLC suite was missing from suite list")

    testcases = json_list(request_json("GET", "/plc-testcases", query={"suite_id": suite_id}, expected_status=200), "PLC testcase list")
    ensure(len(testcases) > 0, "Imported PLC suite did not produce testcase rows")

    targets = json_list(request_json("GET", "/plc-targets", expected_status=200), "PLC target list")
    ensure(any(isinstance(item, dict) and item.get("key") == "stub-local" for item in targets), "stub-local PLC target was not available")

    print_step("Enqueueing stub-local PLC run")
    enqueue = request_json(
        "POST",
        "/plc-test-runs",
        json_body={"suite_id": suite_id, "target_key": "stub-local"},
        expected_status=202,
    )
    enqueue = json_dict(enqueue, "PLC enqueue response")
    run_id = assert_non_empty_string(enqueue.get("job_id"), "PLC run id")
    run = wait_for_plc_run(run_id, timeout_seconds=180)
    ensure(run.get("status") in {"succeeded", "failed"}, f"Unexpected PLC terminal status: {run}")
    summary = json_dict(run.get("summary"), "PLC run summary")
    ensure(int(str(summary.get("total_count") or 0)) > 0, "PLC run summary total_count was zero")

    items = json_list(request_json("GET", f"/plc-test-runs/{run_id}/items", expected_status=200), "PLC run items")
    ensure(len(items) > 0, "PLC run did not produce run items")
    sample_item = json_dict(items[0], "PLC run item payload")
    ensure(sample_item.get("status") in {"passed", "failed", "error"}, "PLC run item had an unexpected status")
    ensure("actual_output_json" in sample_item, "PLC run item did not include actual_output_json")
    ensure("expected_output_json" in sample_item, "PLC run item did not include expected_output_json")

    json_list(request_json("GET", f"/plc-test-runs/{run_id}/io-logs", expected_status=200), "PLC IO logs")
    print_ok("PLC stub pipeline uses deterministic executor logic and does not call an LLM")
    print_ok("PLC stub pipeline smoke passed")


if __name__ == "__main__":
    run_main(main)
