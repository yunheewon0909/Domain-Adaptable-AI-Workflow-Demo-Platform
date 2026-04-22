from __future__ import annotations

from pathlib import Path
import tempfile

from e2e_helpers import (
    assert_non_empty_string,
    choose_workflow_key,
    create_rag_collection,
    ensure,
    get_selectable_model,
    json_dict,
    json_list,
    print_ok,
    print_step,
    request_json,
    run_main,
    timestamp_suffix,
    upload_rag_document,
    wait_for_api_health,
    wait_for_job,
)


def _write_temp_text(contents: str) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="e2e-rag-"))
    path = temp_dir / "workflow-evidence.txt"
    path.write_text(contents, encoding="utf-8")
    return path


def main() -> None:
    wait_for_api_health()
    model = get_selectable_model()
    model_id = assert_non_empty_string(model.get("id"), "selected model id")
    workflow_key = choose_workflow_key()

    collection = create_rag_collection(
        f"E2E Workflow RAG Collection {timestamp_suffix()}",
        "Temporary E2E workflow collection",
    )
    collection_id = assert_non_empty_string(collection.get("id"), "RAG collection id")

    doc_path = _write_temp_text(
        "This E2E document says the platform connects RAG collection documents to workflow reviewer evidence."
    )
    document = upload_rag_document(collection_id, doc_path, "text/plain")
    document_id = assert_non_empty_string(document.get("id"), "RAG document id")
    filename = assert_non_empty_string(document.get("filename"), "RAG document filename")

    print_step(f"Enqueueing workflow={workflow_key} against rag_collection_id={collection_id}")
    enqueue = request_json(
        "POST",
        f"/workflows/{workflow_key}/jobs",
        json_body={
            "dataset_key": None,
            "rag_collection_id": collection_id,
            "prompt": "Summarize the workflow reviewer evidence from this platform document.",
            "k": 4,
            "model_id": model_id,
        },
        expected_status=202,
    )
    enqueue = json_dict(enqueue, "Workflow enqueue response")
    job_id = assert_non_empty_string(enqueue.get("job_id"), "workflow job id")
    job = wait_for_job(job_id, timeout_seconds=180)
    ensure(job.get("status") == "succeeded", f"Workflow job failed: {job}")

    result_json = json_dict(job.get("result_json"), "RAG workflow result_json")
    meta = json_dict(result_json.get("meta"), "RAG workflow result meta")
    ensure(meta.get("source_type") == "rag_collection", "Workflow meta.source_type was not rag_collection")
    ensure(meta.get("rag_collection_id") == collection_id, "Workflow meta.rag_collection_id did not match")
    ensure(meta.get("model_id") == model_id, "Workflow meta.model_id did not match selected model")
    evidence = json_list(result_json.get("evidence"), "RAG workflow evidence")
    ensure(len(evidence) > 0, "RAG workflow result must include evidence")
    ensure(
        any(filename in str(item) or "platform connects RAG collection" in str(item) for item in evidence),
        "RAG workflow evidence did not include the uploaded document filename or excerpt",
    )

    non_empty_answer = any(
        isinstance(result_json.get(key), str) and str(result_json.get(key)).strip()
        for key in ("summary", "rationale", "executive_summary", "title")
    ) or any(
        isinstance(result_json.get(key), list) and len(json_list(result_json.get(key), f"RAG workflow {key}")) > 0
        for key in ("key_points", "recommendations", "findings", "actions")
    )
    ensure(non_empty_answer, "RAG workflow result did not contain a non-empty answer payload")
    print_ok("RAG collection workflow returned evidence and a non-empty result")

    empty_collection = create_rag_collection(
        f"E2E Empty Workflow RAG Collection {timestamp_suffix()}",
        "Empty collection for graceful-result test",
    )
    empty_collection_id = assert_non_empty_string(empty_collection.get("id"), "empty collection id")
    print_step("Verifying graceful empty-collection workflow result")
    empty_enqueue = request_json(
        "POST",
        f"/workflows/{workflow_key}/jobs",
        json_body={
            "rag_collection_id": empty_collection_id,
            "prompt": "Summarize the workflow reviewer evidence from this platform document.",
            "k": 4,
            "model_id": model_id,
        },
        expected_status=202,
    )
    empty_enqueue = json_dict(empty_enqueue, "Empty collection enqueue response")
    empty_job = wait_for_job(assert_non_empty_string(empty_enqueue.get("job_id"), "empty collection workflow job id"), timeout_seconds=120)
    ensure(empty_job.get("status") == "succeeded", "Empty collection workflow should complete gracefully")
    empty_result = json_dict(empty_job.get("result_json"), "Empty collection result_json")
    empty_meta = json_dict(empty_result.get("meta"), "Empty collection result meta")
    ensure(empty_meta.get("rag_status") == "empty", "Empty collection result did not report rag_status=empty")
    ensure(empty_meta.get("degraded") is True, "Empty collection result should be marked degraded")
    ensure(empty_result.get("evidence") == [], "Empty collection result should return empty evidence")

    request_json("DELETE", f"/rag-documents/{document_id}", expected_status=200)
    print_ok("RAG collection workflow smoke passed")


if __name__ == "__main__":
    run_main(main)
