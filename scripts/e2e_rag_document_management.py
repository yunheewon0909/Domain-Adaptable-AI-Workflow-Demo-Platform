from __future__ import annotations

from pathlib import Path
import tempfile

from e2e_helpers import (
    assert_non_empty_string,
    create_rag_collection,
    ensure,
    json_dict,
    json_list,
    print_ok,
    print_step,
    request,
    request_json,
    run_main,
    timestamp_suffix,
    upload_rag_document,
    wait_for_api_health,
)


def _write_temp_text(contents: str) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="e2e-rag-doc-"))
    path = temp_dir / "rag-doc-management.txt"
    path.write_text(contents, encoding="utf-8")
    return path


def main() -> None:
    wait_for_api_health()
    collection = create_rag_collection(
        f"E2E RAG Document CRUD {timestamp_suffix()}",
        "Temporary E2E RAG document management collection",
    )
    collection_id = assert_non_empty_string(collection.get("id"), "RAG collection id")
    text = "This collection document should appear in retrieval preview before deletion and disappear after deletion."
    doc_path = _write_temp_text(text)

    document = upload_rag_document(collection_id, doc_path, "text/plain")
    document_id = assert_non_empty_string(document.get("id"), "RAG document id")

    documents = json_list(request_json("GET", f"/rag-collections/{collection_id}/documents", expected_status=200), "RAG collection document list")
    ensure(any(isinstance(item, dict) and item.get("id") == document_id for item in documents), "Uploaded document was missing from collection list")

    detail = json_dict(request_json("GET", f"/rag-documents/{document_id}", expected_status=200), "RAG document detail")
    ensure(detail.get("id") == document_id, "RAG document detail id did not match")

    preview = request_json(
        "POST",
        "/rag-retrieval/preview",
        json_body={
            "collection_id": collection_id,
            "query": "retrieval preview before deletion",
            "top_k": 3,
        },
        expected_status=200,
    )
    preview = json_dict(preview, "RAG retrieval preview")
    results = json_list(preview.get("results"), "RAG retrieval preview results")
    ensure(len(results) > 0, "RAG retrieval preview did not return the uploaded document")

    print_step("Deleting uploaded RAG document")
    delete_payload = json_dict(request_json("DELETE", f"/rag-documents/{document_id}", expected_status=200), "RAG delete payload")
    ensure(delete_payload.get("deleted") is True, "RAG document delete did not report deleted=true")

    not_found = request("GET", f"/rag-documents/{document_id}", expected_status=404)
    ensure("not found" in not_found.text.lower(), "Deleted RAG document detail did not return 404-style payload")

    documents_after_delete = json_list(request_json("GET", f"/rag-collections/{collection_id}/documents", expected_status=200), "RAG collection document list after delete")
    ensure(not any(isinstance(item, dict) and item.get("id") == document_id for item in documents_after_delete), "Deleted document still appeared in collection list")

    preview_after_delete = request_json(
        "POST",
        "/rag-retrieval/preview",
        json_body={
            "collection_id": collection_id,
            "query": "retrieval preview before deletion",
            "top_k": 3,
        },
        expected_status=200,
    )
    preview_after_delete = json_dict(preview_after_delete, "Post-delete retrieval preview")
    ensure(preview_after_delete.get("results") == [], "Deleted document still appeared in retrieval preview")
    print_ok("RAG document CRUD/retrieval refresh smoke passed")


if __name__ == "__main__":
    run_main(main)
