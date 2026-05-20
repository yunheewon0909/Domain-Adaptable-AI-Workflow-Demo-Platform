"""
title: Domain Adaptable AI Platform - RAG & Workflows
author: Domain Adaptable AI Platform
author_url: https://github.com/
funding_url: https://github.com/
version: 0.1.0
license: MIT
description: >
  Open WebUI Tool that lets a chat call into the platform's RAG collections,
  workflow catalog, and workflow job queue. Connects to the FastAPI service
  at the configured base URL (defaults to http://api:8000 inside the Compose
  network). Does NOT mutate platform data beyond enqueueing a workflow job.

This file is designed to be installed into Open WebUI as a Tool:

  Open WebUI -> Workspace -> Tools -> + (New)
  paste this entire file, set the Valves if needed, then enable the tool on a
  chat. The chat model can then call these methods through Open WebUI's
  function-calling layer.

It is intentionally dependency-light: only stdlib (urllib, json) is used so
that the tool runs inside any Open WebUI container without extra packages.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pydantic import BaseModel, Field


_DEFAULT_BASE_URL = "http://api:8000"
_DEFAULT_TIMEOUT_SECONDS = 30


class Tools:
    """Platform tool surface exposed to Open WebUI chats.

    Each public method becomes a function the chat model can call. Methods
    return JSON-encoded strings so the calling model can read them directly
    without an extra serialization step.
    """

    class Valves(BaseModel):
        api_base_url: str = Field(
            default=_DEFAULT_BASE_URL,
            description=(
                "Base URL of the platform FastAPI service. Default is the "
                "Compose-internal hostname; use http://127.0.0.1:8000 when "
                "running Open WebUI outside the Compose network."
            ),
        )
        request_timeout_seconds: int = Field(
            default=_DEFAULT_TIMEOUT_SECONDS,
            ge=1,
            le=300,
            description="HTTP timeout for every call into the platform API.",
        )
        default_top_k: int = Field(
            default=4,
            ge=1,
            le=10,
            description="Default top_k used for RAG queries when the chat does not specify one.",
        )
        workflow_wait_timeout_seconds: int = Field(
            default=180,
            ge=1,
            le=600,
            description=(
                "Maximum time run_workflow_and_wait waits for an async workflow "
                "job before returning a timeout envelope."
            ),
        )
        workflow_poll_interval_seconds: int = Field(
            default=5,
            ge=1,
            le=30,
            description="Polling interval used by run_workflow_and_wait.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    # ---- helpers -------------------------------------------------------

    def _url(self, path: str) -> str:
        base = self.valves.api_base_url.rstrip("/")
        return f"{base}{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        url = self._url(path)
        data: bytes | None = None
        headers = {"Accept": "application/json"}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method not in ("GET", "POST", "DELETE"):
            return 0, {"error": "unsupported_method", "detail": method}
        req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(
                req, timeout=self.valves.request_timeout_seconds
            ) as response:
                status = response.status
                body_bytes = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            body_bytes = exc.read() if exc.fp is not None else b""
        except urllib.error.URLError as exc:
            return 0, {"error": "request_failed", "detail": str(exc.reason)}
        if not body_bytes:
            return status, None
        try:
            return status, json.loads(body_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            return status, {"raw": body_bytes.decode("utf-8", errors="replace")}

    @staticmethod
    def _format(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _project_collection(item: Any) -> Any:
        # Keep chat-model context lean: drop nested document text_previews,
        # chunking policy, and timestamps from the listing. Reviewers can still
        # call the underlying API for full detail when they actually need it.
        if not isinstance(item, dict):
            return item
        documents = item.get("documents") or []
        document_filenames = [
            doc.get("filename")
            for doc in documents
            if isinstance(doc, dict) and doc.get("filename")
        ]
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "description": item.get("description"),
            "embedding_model": item.get("embedding_model"),
            "document_count": item.get("document_count", len(documents)),
            "document_filenames": document_filenames,
        }

    @staticmethod
    def _project_retrieval(payload: Any) -> Any:
        # Keep the tool result small enough for local chat models to summarize
        # quickly. Full excerpts are useful in the API, but Open WebUI only
        # needs source names, scores, and short snippets for chat grounding.
        if not isinstance(payload, dict):
            return payload
        results = []
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                results.append(item)
                continue
            excerpt = str(item.get("excerpt") or "")
            results.append(
                {
                    "filename": item.get("filename"),
                    "score": item.get("score"),
                    "excerpt": excerpt[:500],
                }
            )
        return {
            "collection_id": payload.get("collection_id"),
            "collection_name": payload.get("collection_name"),
            "query": payload.get("query"),
            "top_k": payload.get("top_k"),
            "results": results,
        }

    @staticmethod
    def _project_document(item: Any) -> Any:
        # Listing projection: drop text_preview and metadata blobs so listing
        # responses stay small. Expose owner_tag and size_bytes (from
        # text_length) so chat models can disambiguate seeded vs uploaded docs.
        if not isinstance(item, dict):
            return item
        metadata = item.get("metadata_json") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        size_bytes = item.get("preview_length")
        if size_bytes is None:
            size_bytes = metadata.get("text_length")
        return {
            "id": item.get("id"),
            "collection_id": item.get("collection_id"),
            "filename": item.get("filename"),
            "mime_type": item.get("mime_type"),
            "source_type": item.get("source_type"),
            "status": item.get("status"),
            "size_bytes": size_bytes,
            "owner_tag": metadata.get("owner_tag"),
        }

    @staticmethod
    def _project_document_detail(item: Any) -> Any:
        # Detail projection: include a truncated text_preview so the chat model
        # can summarize a single document without pulling multi-kilobyte blobs
        # of full text.
        if not isinstance(item, dict):
            return item
        metadata = item.get("metadata_json") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        size_bytes = item.get("preview_length")
        if size_bytes is None:
            size_bytes = metadata.get("text_length")
        text_preview = str(item.get("text_preview") or "")
        return {
            "id": item.get("id"),
            "collection_id": item.get("collection_id"),
            "filename": item.get("filename"),
            "mime_type": item.get("mime_type"),
            "source_type": item.get("source_type"),
            "status": item.get("status"),
            "checksum": item.get("checksum"),
            "size_bytes": size_bytes,
            "owner_tag": metadata.get("owner_tag"),
            "parse_method": item.get("parse_method") or metadata.get("parse_method"),
            "text_preview": text_preview[:1000],
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }

    @staticmethod
    def _project_workflow(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        key = item.get("key")
        result: dict[str, Any] = {
            "key": key,
            "title": item.get("title"),
            "summary": item.get("summary") or item.get("description"),
            "prompt_label": item.get("prompt_label"),
            "output_fields": item.get("output_fields"),
        }
        if key == "briefing":
            result["recommended_prompts"] = [
                "Summarize the latest ops findings",
                "What are the key maintenance issues?",
            ]
        elif key == "recommendation":
            result["recommended_prompts"] = [
                "Recommend improvements based on recent data",
                "What should we prioritize this week?",
            ]
        elif key == "report_generator":
            result["recommended_prompts"] = [
                "Generate a report on the current status",
                "Create a weekly ops summary",
            ]
        return result

    @staticmethod
    def _project_dataset(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        return {
            "dataset_key": item.get("dataset_key") or item.get("key"),
            "name": item.get("name"),
            "description": item.get("description"),
        }

    @staticmethod
    def _project_model(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        readiness = item.get("readiness") if isinstance(item.get("readiness"), dict) else {}
        return {
            "model_id": item.get("id"),
            "name": item.get("display_name"),
            "description": item.get("description"),
            "status": item.get("status"),
            "publish_status": item.get("publish_status"),
            "source_type": item.get("source_type"),
            "tags": item.get("tags_json") or [],
            "selectable": readiness.get("selectable", False) if isinstance(readiness, dict) else False,
            "selectable_reason": readiness.get("selectable_reason") if isinstance(readiness, dict) else None,
        }

    @staticmethod
    def _project_job(item: Any) -> Any:
        # Drop payload_json (the request input the chat already knows) so the
        # polling response stays small and result_json stands out.
        if not isinstance(item, dict):
            return item
        # The enqueue endpoint returns a compact acknowledgement with
        # ``job_id`` at top level, while the status endpoint returns the full
        # job resource with ``id``. Normalize both shapes so chat follow-up and
        # run_workflow_and_wait never lose the real job identifier.
        return {
            "id": item.get("id") or item.get("job_id"),
            "status": item.get("status"),
            "workflow_key": item.get("workflow_key"),
            "dataset_key": item.get("dataset_key"),
            "attempts": item.get("attempts"),
            "max_attempts": item.get("max_attempts"),
            "error": item.get("error"),
            "result_json": item.get("result_json"),
            "created_at": item.get("created_at"),
            "started_at": item.get("started_at"),
            "finished_at": item.get("finished_at"),
        }

    @staticmethod
    def _summarize_result(result_json: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(result_json, dict):
            return {"result": result_json}
        internal_keys = {"timing", "raw", "meta", "request", "payload"}
        summary: dict[str, Any] = {
            key: value for key, value in result_json.items() if key not in internal_keys
        }
        if not summary:
            summary["result"] = result_json
        return summary

    def _error(self, status: int, body: Any, *, action: str) -> str:
        return self._format(
            {
                "ok": False,
                "action": action,
                "http_status": status,
                "platform_response": body,
                "hint": (
                    "Check that api_base_url is reachable from the Open WebUI "
                    "container. Inside Compose use http://api:8000, on the host "
                    "use http://127.0.0.1:8000."
                ),
            }
        )

    # ---- RAG collections ----------------------------------------------

    def list_rag_collections(self) -> str:
        """List the platform's RAG collections.

        Use this when the user asks "what RAG collections are available",
        "which knowledge bases exist", or before calling query_rag_collection.

        :return: JSON string describing each collection (id, name, document
            counts). Empty list means the platform has no collections yet.
        """
        status, body = self._request("GET", "/rag-collections")
        if status != 200:
            return self._error(status, body, action="list_rag_collections")
        collections = (
            [self._project_collection(item) for item in body]
            if isinstance(body, list)
            else body
        )
        return self._format({"ok": True, "collections": collections})

    def query_rag_collection(
        self,
        collection_id: str,
        query: str,
        top_k: int | None = None,
    ) -> str:
        """Run a retrieval preview against one RAG collection.

        Use this to ground an answer in a specific platform RAG collection
        before responding to the user. The result includes the top matching
        chunks with filenames and excerpts; the chat model should cite these
        in its final answer.

        :param collection_id: Collection id from list_rag_collections.
        :param query: Natural-language query to embed and search with.
        :param top_k: How many chunks to return. Defaults to the Valve's
            default_top_k. Clamped to 1..10 by the platform.
        :return: JSON string with the top matches, or an error envelope.
        """
        effective_top_k = int(top_k) if top_k is not None else self.valves.default_top_k
        effective_top_k = max(1, min(effective_top_k, 10))
        status, body = self._request(
            "POST",
            "/rag-retrieval/preview",
            json_body={
                "collection_id": collection_id,
                "query": query,
                "top_k": effective_top_k,
            },
        )
        if status != 200:
            return self._error(status, body, action="query_rag_collection")
        return self._format({"ok": True, "retrieval": self._project_retrieval(body)})

    def get_rag_collection(self, collection_id: str) -> str:
        """Fetch full detail for one RAG collection.

        Use this when the user asks "tell me about collection X", "describe
        the Ops handbook collection", or otherwise wants more than the compact
        list_rag_collections projection. The returned envelope includes the
        collection's embedding model, chunking policy, document count, and
        timestamps.

        :param collection_id: Collection id from list_rag_collections.
        :return: JSON string with full collection detail, or an error envelope
            when the collection does not exist.
        """
        encoded_id = urllib.parse.quote(collection_id, safe="")
        status, body = self._request("GET", f"/rag-collections/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="get_rag_collection")
        return self._format({"ok": True, "collection": body})

    def list_rag_documents(self, collection_id: str) -> str:
        """List documents belonging to a RAG collection.

        Use this when the user asks "what's in collection X", "show me the
        files in the Ops handbook", or before calling get_rag_document /
        delete_rag_document. Returns a compact projection (id, filename,
        mime_type, size_bytes, owner_tag) with text_preview omitted to keep
        the chat context lean.

        :param collection_id: Collection id from list_rag_collections.
        :return: JSON string with the document list, or an error envelope when
            the collection does not exist.
        """
        encoded_id = urllib.parse.quote(collection_id, safe="")
        status, body = self._request(
            "GET", f"/rag-collections/{encoded_id}/documents"
        )
        if status != 200:
            return self._error(status, body, action="list_rag_documents")
        documents = (
            [self._project_document(item) for item in body]
            if isinstance(body, list)
            else body
        )
        return self._format(
            {"ok": True, "collection_id": collection_id, "documents": documents}
        )

    def get_rag_document(self, document_id: str) -> str:
        """Fetch full detail for one RAG document.

        Use this when the user asks "what does document X contain" or wants
        the parsed preview of a specific file. The returned envelope includes
        a text_preview truncated to 1000 characters; for longer excerpts run
        query_rag_collection instead.

        :param document_id: Document id from list_rag_documents.
        :return: JSON string with document detail, or an error envelope when
            the document does not exist.
        """
        encoded_id = urllib.parse.quote(document_id, safe="")
        status, body = self._request("GET", f"/rag-documents/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="get_rag_document")
        return self._format(
            {"ok": True, "document": self._project_document_detail(body)}
        )

    def delete_rag_document(self, document_id: str) -> str:
        """Delete a RAG document. DESTRUCTIVE; confirm with the user first.

        This permanently removes the document record and its stored file from
        the platform; the chunks are removed from retrieval on the next
        reindex. Always confirm the user's intent before calling this; the
        operation cannot be undone.

        :param document_id: Document id from list_rag_documents.
        :return: JSON string with a confirmation envelope (deleted=true,
            storage_deleted, collection_id), or an error envelope when the
            document does not exist.
        """
        encoded_id = urllib.parse.quote(document_id, safe="")
        status, body = self._request("DELETE", f"/rag-documents/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="delete_rag_document")
        result = body if isinstance(body, dict) else {"raw": body}
        return self._format(
            {
                "ok": True,
                "action": "delete_rag_document",
                "document_id": result.get("document_id") or document_id,
                "collection_id": result.get("collection_id"),
                "deleted": bool(result.get("deleted", True)),
                "storage_deleted": bool(result.get("storage_deleted", False)),
            }
        )

    # ---- Workflows -----------------------------------------------------

    def list_workflows(self) -> str:
        """List the platform's workflow catalog.

        Use this when the user asks what platform workflows can be run,
        or before calling enqueue_workflow_job. The returned list includes
        each workflow's key, title, prompt label, and output fields.

        :return: JSON string with the workflow catalog.
        """
        status, body = self._request("GET", "/workflows")
        if status != 200:
            return self._error(status, body, action="list_workflows")
        workflows = (
            [self._project_workflow(item) for item in body]
            if isinstance(body, list)
            else body
        )
        return self._format({"ok": True, "workflows": workflows})

    def list_workflow_sources(self) -> str:
        """List available workflow sources: RAG collections and legacy datasets."""
        rag_status, rag_body = self._request("GET", "/rag-collections")
        if rag_status != 200:
            return self._error(rag_status, rag_body, action="list_workflow_sources.rag_collections")
        rag_collections = (
            [self._project_collection(item) for item in rag_body]
            if isinstance(rag_body, list)
            else rag_body
        )

        ds_status, ds_body = self._request("GET", "/datasets")
        if ds_status != 200:
            return self._error(ds_status, ds_body, action="list_workflow_sources.datasets")
        datasets = (
            [self._project_dataset(item) for item in ds_body]
            if isinstance(ds_body, list)
            else ds_body
        )

        return self._format(
            {
                "ok": True,
                "sources": {
                    "rag_collections": rag_collections,
                    "datasets": datasets,
                },
            }
        )

    def list_selectable_models(self) -> str:
        """List platform models that are ready for inference selection."""
        status, body = self._request("GET", "/models")
        if status != 200:
            return self._error(status, body, action="list_selectable_models")
        raw_models = body if isinstance(body, list) else []
        selectable = [
            self._project_model(item)
            for item in raw_models
            if isinstance(item, dict)
            and isinstance(item.get("readiness"), dict)
            and item["readiness"].get("selectable", False)
        ]
        return self._format({"ok": True, "models": selectable})

    # ---- Models registry ----------------------------------------------

    def list_platform_models(self, include_review_only: bool = False) -> str:
        """List platform models from the registry.

        Use this when the user asks "what models are available", "which models
        can I run", or before calling get_model_detail / run_platform_inference.
        By default only selectable models are returned; set include_review_only
        to True to also include models still in review or not yet published.

        :param include_review_only: When False (default), only readiness.selectable
            models are returned. When True, all registry entries are returned.
        :return: JSON string with the projected model list, total count, and
            selectable_count.
        """
        status, body = self._request("GET", "/models")
        if status != 200:
            return self._error(status, body, action="list_platform_models")
        raw_models = body if isinstance(body, list) else []
        dict_models = [item for item in raw_models if isinstance(item, dict)]
        selectable_count = sum(
            1
            for item in dict_models
            if isinstance(item.get("readiness"), dict)
            and item["readiness"].get("selectable", False)
        )
        if include_review_only:
            filtered = dict_models
        else:
            filtered = [
                item
                for item in dict_models
                if isinstance(item.get("readiness"), dict)
                and item["readiness"].get("selectable", False)
            ]
        models = [self._project_model(item) for item in filtered]
        return self._format(
            {
                "ok": True,
                "models": models,
                "total": len(dict_models),
                "selectable_count": selectable_count,
            }
        )

    def get_model_detail(self, model_id: str) -> str:
        """Fetch full detail for one platform model.

        Use this when the user asks "tell me about model X" or wants warnings,
        timestamps, and full projected fields. Returns the projected model plus
        warnings, created_at, updated_at.

        :param model_id: Model id from list_platform_models.
        :return: JSON string with model detail, or an error envelope on 404.
        """
        encoded_id = urllib.parse.quote(model_id, safe="")
        status, body = self._request("GET", f"/models/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="get_model_detail")
        projected = self._project_model(body) if isinstance(body, dict) else {}
        if isinstance(projected, dict) and isinstance(body, dict):
            projected["warnings"] = body.get("warnings") or []
            projected["created_at"] = body.get("created_at")
            projected["updated_at"] = body.get("updated_at")
        return self._format({"ok": True, "model": projected})

    def get_model_lineage(self, model_id: str) -> str:
        """Fetch lineage metadata for one platform model.

        Use this when the user asks about a model's base model, trainer,
        artifact, or published name. Returns the raw lineage dict from the
        platform unchanged (it is already compact).

        :param model_id: Model id from list_platform_models.
        :return: JSON string with the lineage dict, or an error envelope on 404.
        """
        encoded_id = urllib.parse.quote(model_id, safe="")
        status, body = self._request("GET", f"/models/{encoded_id}/lineage")
        if status != 200:
            return self._error(status, body, action="get_model_lineage")
        return self._format({"ok": True, "lineage": body})

    def run_platform_inference(
        self,
        model_id: str,
        prompt: str,
        rag_collection_id: str | None = None,
        top_k: int | None = None,
    ) -> str:
        """Run a single-turn inference against a platform model.

        Use this when the user wants a direct answer from a specific platform
        model, optionally grounded in a RAG collection. For evidence-grounded
        multi-step workflows prefer run_workflow_and_wait instead.

        :param model_id: Model id from list_platform_models (must be selectable).
        :param prompt: User prompt to send to the model.
        :param rag_collection_id: Optional RAG collection id for grounding.
        :param top_k: Optional retrieval top_k (only meaningful with
            rag_collection_id). Clamped to 1..10.
        :return: JSON string with the answer and model_id, or an error envelope
            on failure (Ollama down, invalid model, etc.).
        """
        body_payload: dict[str, Any] = {"model_id": model_id, "prompt": prompt}
        if rag_collection_id is not None:
            body_payload["rag_collection_id"] = rag_collection_id
        if top_k is not None:
            body_payload["top_k"] = max(1, min(int(top_k), 10))
        status, body = self._request("POST", "/inference/run", json_body=body_payload)
        if status != 200:
            return self._error(status, body, action="run_platform_inference")
        if not isinstance(body, dict):
            return self._format({"ok": True, "answer": None, "model_id": model_id, "raw": body})
        return self._format(
            {
                "ok": True,
                "answer": body.get("answer"),
                "model_id": body.get("model_id") or model_id,
                "usage": body.get("usage"),
            }
        )

    def enqueue_workflow_job(
        self,
        workflow_key: str,
        prompt: str,
        dataset_key: str | None = None,
        rag_collection_id: str | None = None,
        model_id: str | None = None,
        top_k: int | None = None,
    ) -> str:
        """Enqueue a platform workflow run as an async job.

        This is fire-and-forget: it returns a job id immediately, and the
        worker process executes the workflow asynchronously. Use
        get_job_status with the returned job_id to poll for completion and
        read the final result_json.

        Most evidence-grounded workflows require either ``dataset_key`` or
        ``rag_collection_id``; if both are omitted the platform may return a
        404 error envelope. Prefer ``rag_collection_id`` from
        list_rag_collections when available.

        :param workflow_key: Workflow key from list_workflows().
        :param prompt: User prompt to drive the workflow.
        :param dataset_key: Optional legacy dataset_key for evidence retrieval.
        :param rag_collection_id: Optional RAG collection id for grounding.
        :param model_id: Optional platform model registry id; defaults to the
            platform's default selectable model when omitted.
        :param top_k: Optional retrieval top_k.
        :return: JSON string with at least job_id and status (typically
            "queued"). Call get_job_status(job_id) to fetch the result.
        """
        body_payload: dict[str, Any] = {"prompt": prompt}
        if dataset_key is not None:
            body_payload["dataset_key"] = dataset_key
        if rag_collection_id is not None:
            body_payload["rag_collection_id"] = rag_collection_id
        if model_id is not None:
            body_payload["model_id"] = model_id
        if top_k is not None:
            body_payload["k"] = max(1, min(int(top_k), 8))

        encoded_key = urllib.parse.quote(workflow_key, safe="")
        status, body = self._request(
            "POST",
            f"/workflows/{encoded_key}/jobs",
            json_body=body_payload,
        )
        if status not in (200, 202):
            return self._error(status, body, action="enqueue_workflow_job")
        job = self._project_job(body)
        job_id = job.get("id") if isinstance(job, dict) else None
        source_type: str | None = None
        if rag_collection_id is not None:
            source_type = "rag"
        elif dataset_key is not None:
            source_type = "dataset"
        return self._format(
            {
                "ok": True,
                "job_id": job_id,
                "status": job.get("status") if isinstance(job, dict) else None,
                "workflow_key": job.get("workflow_key") if isinstance(job, dict) else workflow_key,
                "source_type": source_type,
                "model_id": model_id,
                "rag_collection_id": rag_collection_id,
                "dataset_key": dataset_key,
                "job": job,
                "next_step": (
                    f"Call get_job_status with job_id={job_id!r}; do not use a "
                    "placeholder. Poll until status is 'succeeded' or 'failed'."
                ),
            }
        )

    def run_workflow_and_wait(
        self,
        workflow_key: str,
        prompt: str,
        dataset_key: str | None = None,
        rag_collection_id: str | None = None,
        model_id: str | None = None,
        top_k: int | None = None,
        max_wait_seconds: int | None = None,
    ) -> str:
        """Enqueue a workflow and wait for its final status in one tool call.

        Prefer this for Open WebUI chat UX when the user asks to run a
        workflow and see the result, because it avoids fragile multi-turn
        polling and prevents placeholder job ids. It returns the compact final
        job, including result_json when status is "succeeded". If the job is
        still running after the wait budget, it returns ok=true with status
        "timeout" and the real job_id so the user can later call
        get_job_status(job_id).

        :param workflow_key: Workflow key from list_workflows().
        :param prompt: User prompt to drive the workflow.
        :param dataset_key: Optional legacy dataset_key for evidence retrieval.
        :param rag_collection_id: Optional RAG collection id for grounding.
        :param model_id: Optional platform model registry id.
        :param top_k: Optional retrieval top_k.
        :param max_wait_seconds: Optional per-call wait budget, clamped by the
            Valve's workflow_wait_timeout_seconds.
        :return: JSON string with job_id, final/timeout status, and compact job.
        """
        body_payload: dict[str, Any] = {"prompt": prompt}
        if dataset_key is not None:
            body_payload["dataset_key"] = dataset_key
        if rag_collection_id is not None:
            body_payload["rag_collection_id"] = rag_collection_id
        if model_id is not None:
            body_payload["model_id"] = model_id
        if top_k is not None:
            body_payload["k"] = max(1, min(int(top_k), 8))

        encoded_key = urllib.parse.quote(workflow_key, safe="")
        status, body = self._request(
            "POST",
            f"/workflows/{encoded_key}/jobs",
            json_body=body_payload,
        )
        if status not in (200, 202):
            return self._error(status, body, action="run_workflow_and_wait.enqueue")

        job = self._project_job(body)
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return self._format(
                {
                    "ok": False,
                    "action": "run_workflow_and_wait.enqueue",
                    "error": "missing_job_id",
                    "job": job,
                }
            )

        configured_budget = int(self.valves.workflow_wait_timeout_seconds)
        if max_wait_seconds is not None:
            configured_budget = min(configured_budget, max(1, int(max_wait_seconds)))
        poll_interval = int(self.valves.workflow_poll_interval_seconds)
        deadline = time.monotonic() + configured_budget

        while True:
            current_status = job.get("status") if isinstance(job, dict) else None
            if current_status in ("succeeded", "failed", "cancelled"):
                return self._format(
                    {
                        "ok": current_status == "succeeded",
                        "job_id": job_id,
                        "status": current_status,
                        "job": job,
                    }
                )
            if time.monotonic() >= deadline:
                return self._format(
                    {
                        "ok": True,
                        "job_id": job_id,
                        "status": "timeout",
                        "job": job,
                        "next_step": f"Call get_job_status with job_id={job_id!r} later.",
                    }
                )
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
            encoded_id = urllib.parse.quote(str(job_id), safe="")
            status, body = self._request("GET", f"/jobs/{encoded_id}")
            if status != 200:
                return self._error(status, body, action="run_workflow_and_wait.poll")
            job = self._project_job(body)

    # ---- Jobs ----------------------------------------------------------

    def get_job_status(self, job_id: str) -> str:
        """Fetch the current status of a platform job.

        Use this after enqueue_workflow_job to poll for completion. When
        status is "succeeded" the result_json field carries the workflow
        output. When status is "failed" the error field explains why.

        :param job_id: Job id returned by enqueue_workflow_job.
        :return: JSON string describing the job (status, attempts, error,
            result_json, timestamps).
        """
        encoded_id = urllib.parse.quote(job_id, safe="")
        status, body = self._request("GET", f"/jobs/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="get_job_status")
        return self._format({"ok": True, "job": self._project_job(body)})

    def summarize_job_result(self, job_id: str) -> str:
        """Return a concise summary of a workflow job result."""
        encoded_id = urllib.parse.quote(job_id, safe="")
        status, body = self._request("GET", f"/jobs/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="summarize_job_result")
        job = self._project_job(body) if isinstance(body, dict) else {}
        job_status = job.get("status") if isinstance(job, dict) else None
        if job_status == "succeeded":
            result_json = job.get("result_json") if isinstance(job, dict) else None
            summary = self._summarize_result(result_json)
            return self._format(
                {
                    "ok": True,
                    "job_id": job_id,
                    "status": job_status,
                    "summary": summary,
                }
            )
        if job_status == "failed":
            error = job.get("error") if isinstance(job, dict) else None
            return self._format(
                {
                    "ok": False,
                    "job_id": job_id,
                    "status": job_status,
                    "error": error,
                    "suggestion": "Check the job inputs and retry, or inspect the platform logs.",
                }
            )
        return self._format(
            {
                "ok": True,
                "job_id": job_id,
                "status": job_status,
                "summary": None,
                "next_step": f"Call get_job_status with job_id={job_id!r} to poll again.",
            }
        )
