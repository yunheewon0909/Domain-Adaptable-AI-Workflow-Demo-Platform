#!/usr/bin/env python3
"""E2E: full Graph RAG evaluation run + report.

create collection -> upload -> index -> generate eval set -> run evaluation ->
fetch report. Host-side: requires the compose stack (api + worker + ollama).
Run: ``python scripts/e2e_rag_evaluation_report_smoke.py``.
"""

from __future__ import annotations

from e2e_helpers import (
    create_rag_collection,
    ensure,
    json_dict,
    print_ok,
    print_step,
    request_json,
    run_main,
    timestamp_suffix,
    wait_for_api_health,
    wait_for_job,
)


def _index(collection_id: str) -> None:
    enqueue = json_dict(
        request_json("POST", f"/rag-collections/{collection_id}/index", expected_status=202),
        "index enqueue",
    )
    job = wait_for_job(str(json_dict(enqueue["job"], "job")["id"]), timeout_seconds=300)
    ensure(job.get("status") == "succeeded", f"index job did not succeed: {job}")


def main() -> None:
    wait_for_api_health()

    collection = create_rag_collection(f"e2e-report-{timestamp_suffix()}")
    collection_id = str(collection["id"])
    request_json(
        "POST",
        f"/rag-collections/{collection_id}/documents/text",
        json_body={
            "filename": "notes.md",
            "content": "Pump P-101 feeds Reactor R-200. The reactor produces ethylene.",
        },
        expected_status=201,
    )

    print_step("Index the collection")
    _index(collection_id)

    print_step("Generate an evaluation set")
    gen = json_dict(
        request_json(
            "POST",
            "/evaluation-sets/from-collection",
            json_body={"collection_id": collection_id, "name": "E2E report set"},
            expected_status=201,
        ),
        "evaluation set",
    )
    set_id = str(gen["evaluation_set_id"])

    print_step("Run the evaluation + wait for the job")
    run = json_dict(
        request_json(
            "POST",
            "/evaluation-runs",
            json_body={"evaluation_set_id": set_id, "mode": "local"},
            expected_status=202,
        ),
        "evaluation run",
    )
    run_id = str(json_dict(run["run"], "run")["id"])
    job = wait_for_job(str(json_dict(run["job"], "job")["id"]), timeout_seconds=300)
    ensure(job.get("status") == "succeeded", f"evaluation job did not succeed: {job}")

    print_step("Fetch the report")
    report = json_dict(
        request_json("GET", f"/evaluation-runs/{run_id}/report", expected_status=200),
        "report",
    )
    run_payload = json_dict(report["run"], "run")
    ensure(run_payload.get("status") == "succeeded", f"run not succeeded: {run_payload}")
    report_body = json_dict(report["report"], "report body")
    ensure("answer_quality" in report_body, "report missing answer_quality")
    ensure("retrieval_quality" in report_body, "report missing retrieval_quality")
    ensure("collection_health" in report_body, "report missing collection_health")
    print_ok(
        f"report: {report_body.get('question_count')} questions, "
        f"groundedness={report_body['answer_quality'].get('avg_groundedness')}, "
        f"coverage={report_body['retrieval_quality'].get('source_coverage')}"
    )


if __name__ == "__main__":
    run_main(main)
