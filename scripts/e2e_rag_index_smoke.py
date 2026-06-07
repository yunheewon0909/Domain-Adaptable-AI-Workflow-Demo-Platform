#!/usr/bin/env python3
"""E2E: create a collection, index it (Graph RAG), and query it.

Host-side: requires the compose stack (api + worker + ollama) running, with a
chat + embedding model pulled into Ollama so graph extraction has something to
work with. Run: ``python scripts/e2e_rag_index_smoke.py``.
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


def main() -> None:
    wait_for_api_health()

    print_step("Create collection + add a text document")
    collection = create_rag_collection(f"e2e-index-{timestamp_suffix()}")
    collection_id = str(collection["id"])
    request_json(
        "POST",
        f"/rag-collections/{collection_id}/documents/text",
        json_body={
            "filename": "notes.md",
            "content": (
                "Pump P-101 feeds Reactor R-200. Reactor R-200 produces ethylene. "
                "Operator Dana inspects Pump P-101 weekly."
            ),
        },
        expected_status=201,
    )
    print_ok(f"collection {collection_id} seeded")

    print_step("Enqueue Graph RAG index job + wait for it")
    enqueue = json_dict(
        request_json(
            "POST", f"/rag-collections/{collection_id}/index", expected_status=202
        ),
        "index enqueue",
    )
    job_id = str(json_dict(enqueue["job"], "job")["id"])
    job = wait_for_job(job_id, timeout_seconds=300)
    ensure(job.get("status") == "succeeded", f"index job did not succeed: {job}")
    print_ok("index job succeeded")

    print_step("Query the collection (local graph retrieval)")
    result = json_dict(
        request_json(
            "POST",
            f"/rag-collections/{collection_id}/query",
            json_body={"query": "What does pump P-101 feed?", "mode": "local"},
            expected_status=200,
        ),
        "query result",
    )
    ensure(result.get("mode") == "local", f"unexpected query result: {result}")
    ensure("trace_id" in result, "query must record a retrieval trace")
    print_ok(
        f"query returned {len(result.get('chunks') or [])} chunk(s), "
        f"{len(result.get('entities') or [])} entity(ies); trace={result.get('trace_id')}"
    )

    print_step("Inspect the subgraph")
    subgraph = json_dict(
        request_json(
            "GET", f"/rag-collections/{collection_id}/subgraph", expected_status=200
        ),
        "subgraph",
    )
    print_ok(
        f"subgraph: {len(subgraph.get('nodes') or [])} nodes, "
        f"{len(subgraph.get('edges') or [])} edges"
    )


if __name__ == "__main__":
    run_main(main)
