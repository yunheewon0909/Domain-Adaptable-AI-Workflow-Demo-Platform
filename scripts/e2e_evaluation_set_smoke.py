#!/usr/bin/env python3
"""E2E: generate a reviewable evaluation set from an indexed collection.

Host-side: requires the compose stack (api + worker + ollama) running.
Run: ``python scripts/e2e_evaluation_set_smoke.py``.
"""

from __future__ import annotations

from e2e_helpers import (
    create_rag_collection,
    ensure,
    json_dict,
    json_list,
    print_ok,
    print_step,
    request_json,
    run_main,
    timestamp_suffix,
    wait_for_api_health,
    wait_for_job,
)


def main() -> None:
    wait_for_api_health()

    collection = create_rag_collection(f"e2e-eval-{timestamp_suffix()}")
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
    enqueue = json_dict(
        request_json("POST", f"/rag-collections/{collection_id}/index", expected_status=202),
        "index enqueue",
    )
    job = wait_for_job(str(json_dict(enqueue["job"], "job")["id"]), timeout_seconds=300)
    ensure(job.get("status") == "succeeded", f"index job did not succeed: {job}")

    print_step("Generate an evaluation set from the collection")
    gen = json_dict(
        request_json(
            "POST",
            "/evaluation-sets/from-collection",
            json_body={
                "collection_id": collection_id,
                "name": "E2E eval set",
                "questions_per_chunk": 2,
            },
            expected_status=201,
        ),
        "evaluation set",
    )
    set_id = str(gen["evaluation_set_id"])
    ensure(int(gen.get("question_count") or 0) >= 1, f"no questions generated: {gen}")
    print_ok(f"generated {gen['question_count']} question(s) in set {set_id}")

    print_step("Fetch the set + verify source-chunk linkage")
    detail = json_dict(
        request_json("GET", f"/evaluation-sets/{set_id}", expected_status=200),
        "set detail",
    )
    questions = json_list(detail.get("questions"), "questions")
    ensure(bool(questions), "evaluation set has no questions")
    ensure(
        all(q.get("source_chunk_id") for q in questions if isinstance(q, dict)),
        "every generated question must link to a source chunk",
    )
    print_ok("all questions link to a source chunk")

    print_step("Accept the first question (review workflow)")
    q_id = str(json_dict(questions[0], "question")["id"])
    accepted = json_dict(
        request_json(
            "PATCH",
            f"/evaluation-questions/{q_id}",
            json_body={"status": "accepted"},
            expected_status=200,
        ),
        "accepted question",
    )
    ensure(accepted.get("status") == "accepted", f"accept failed: {accepted}")
    print_ok("question accepted")


if __name__ == "__main__":
    run_main(main)
