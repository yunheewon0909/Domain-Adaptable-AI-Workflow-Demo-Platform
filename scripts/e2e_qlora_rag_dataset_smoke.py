"""End-to-end smoke for the headline QLoRA-on-RAG-collection feature.

Exercises:
1. POST /rag-collections                 — create a collection
2. POST /rag-collections/{id}/documents  — upload a small text document
3. POST /ft-datasets/from-rag-collection — generate Q/A pairs via LM Studio
4. GET  /ft-dataset-versions/{id}/rows   — confirm rows were written

Requires:
- API running locally (default http://127.0.0.1:8000)
- LM Studio reachable with a chat model loaded (or the call will fail)

Run from repo root:
    python scripts/e2e_qlora_rag_dataset_smoke.py
"""

from __future__ import annotations

from e2e_helpers import (
    assert_non_empty_string,
    ensure,
    json_dict,
    json_list,
    print_ok,
    print_step,
    request_json,
    request_multipart,
    run_main,
    timestamp_suffix,
    wait_for_api_health,
)


_SAMPLE_TEXT = (
    "Solar plant maintenance requires monthly panel cleaning, quarterly inverter "
    "inspections, and annual lubrication of tracker bearings. Operators should log "
    "each inspection in the maintenance handbook and flag any alarm codes for "
    "review the next business day. Replacement parts (fuses, contactors, surge "
    "protectors) are tracked in the spares ledger; restock when inventory falls "
    "below the two-week safety threshold."
)


def main() -> None:
    wait_for_api_health()

    print_step("Creating RAG collection")
    suffix = timestamp_suffix()
    create_resp = request_json(
        "POST",
        "/rag-collections",
        json_body={"name": f"QLoRA RAG smoke {suffix}"},
        expected_status=201,
    )
    collection = json_dict(create_resp, "RAG collection response")
    collection_id = assert_non_empty_string(collection.get("id"), "rag collection id")
    print_ok(f"created collection {collection_id}")

    print_step("Uploading sample document")
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(
        prefix="qlora-rag-smoke-",
        suffix=".txt",
        mode="w",
        delete=False,
        encoding="utf-8",
    ) as fh:
        fh.write(_SAMPLE_TEXT)
        sample_path = Path(fh.name)

    upload_resp = request_multipart(
        "POST",
        f"/rag-collections/{collection_id}/documents",
        fields={},
        files=[("file", sample_path, "text/plain")],
        expected_status=201,
    )
    document = json_dict(upload_resp.json(), "RAG document response")
    document_id = assert_non_empty_string(document.get("id"), "rag document id")
    print_ok(f"uploaded document {document_id}")

    print_step("Generating Q/A dataset from RAG collection")
    dataset_resp = request_json(
        "POST",
        "/ft-datasets/from-rag-collection",
        json_body={
            "rag_collection_id": collection_id,
            "dataset_name": f"QLoRA RAG smoke dataset {suffix}",
            "version_label": "v1",
            "max_chunks": 4,
            "pairs_per_chunk": 2,
            "chunk_chars": 800,
        },
        expected_status=201,
    )
    payload = json_dict(dataset_resp, "dataset-from-RAG response")
    dataset_id = assert_non_empty_string(payload.get("dataset_id"), "dataset_id")
    version_id = assert_non_empty_string(
        payload.get("dataset_version_id"), "dataset_version_id"
    )
    row_count = payload.get("row_count")
    ensure(
        isinstance(row_count, int) and row_count > 0,
        f"expected row_count > 0, got {row_count}",
    )
    print_ok(
        f"dataset {dataset_id} version {version_id}: {row_count} rows "
        f"from {payload.get('chunk_count')} chunk(s) "
        f"({payload.get('rejected_chunk_count')} chunk error(s))"
    )

    print_step("Fetching dataset rows")
    rows_resp = request_json(
        "GET", f"/ft-dataset-versions/{version_id}/rows", expected_status=200
    )
    rows = json_list(rows_resp, "dataset rows response")
    ensure(len(rows) == row_count, "row count mismatch between response and listing")
    sample = rows[0]
    ensure(
        isinstance(sample, dict)
        and isinstance(sample.get("input_json"), dict)
        and sample["input_json"].get("instruction"),
        "first row must carry instruction in input_json",
    )
    ensure(
        isinstance(sample.get("target_json"), dict)
        and sample["target_json"].get("output"),
        "first row must carry output in target_json",
    )
    metadata = sample.get("metadata_json") or {}
    ensure(
        metadata.get("source") == "rag_collection"
        and metadata.get("rag_collection_id") == collection_id,
        "metadata_json must record rag_collection source",
    )
    print_ok(
        f"first row instruction: {sample['input_json']['instruction'][:60]!r}"
    )

    print_ok("QLoRA-on-RAG dataset smoke passed")


if __name__ == "__main__":
    run_main(main)
