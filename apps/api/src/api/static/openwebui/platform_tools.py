"""
title: Domain Adaptable AI Platform - RAG, Models, FT
author: Domain Adaptable AI Platform
author_url: https://github.com/
funding_url: https://github.com/
version: 0.1.0
license: MIT
description: >
  Open WebUI Tool that lets a chat call into the platform's RAG
  collections, model registry, and fine-tuning catalog. Connects to
  the FastAPI service at the configured base URL (defaults to
  http://host.docker.internal:8000 so a Docker-hosted Open WebUI
  reaches the Mac host). Read-only by default; deletes a RAG
  document only when the chat explicitly invokes delete_rag_document.

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


_DEFAULT_BASE_URL = "http://host.docker.internal:8000"
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
                "Base URL of the platform FastAPI service. Default targets "
                "the Mac host from a Docker-hosted Open WebUI; use "
                "http://127.0.0.1:8000 when Open WebUI runs on the same Mac, "
                "or the LAN / Tailscale address for remote clients."
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
        return {
            "id": item.get("id") or item.get("job_id"),
            "type": item.get("type"),
            "status": item.get("status"),
            "attempts": item.get("attempts"),
            "max_attempts": item.get("max_attempts"),
            "error": item.get("error"),
            "result_json": item.get("result_json"),
            "created_at": item.get("created_at"),
            "started_at": item.get("started_at"),
            "finished_at": item.get("finished_at"),
        }

    @staticmethod
    def _project_ft_dataset(item: Any) -> Any:
        # Listing projection: drop nested versions/rows so the chat picker stays
        # compact. version_count is derived from the embedded versions list.
        if not isinstance(item, dict):
            return item
        versions = item.get("versions") or []
        return {
            "dataset_id": item.get("id"),
            "name": item.get("name"),
            "description": item.get("description"),
            "version_count": len(versions) if isinstance(versions, list) else 0,
            "created_at": item.get("created_at"),
        }

    @staticmethod
    def _project_ft_version(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        return {
            "version_id": item.get("id"),
            "version_number": item.get("version_label"),
            "status": item.get("status"),
            "row_count": item.get("row_count"),
            "created_at": item.get("created_at"),
        }

    @staticmethod
    def _project_ft_training_job(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        return {
            "job_id": item.get("id"),
            "status": item.get("status"),
            "dataset_name": item.get("dataset_name"),
            "base_model": item.get("base_model_name"),
            "training_method": item.get("training_method"),
            "created_at": item.get("created_at"),
            "finished_at": item.get("finished_at"),
        }

    @staticmethod
    def _project_ft_training_job_detail(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        base = Tools._project_ft_training_job(item)
        if not isinstance(base, dict):
            return base
        artifacts = item.get("artifacts") or []
        artifact_id: str | None = None
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict) and artifact.get("id"):
                    artifact_id = artifact.get("id")
                    break
        error_json = item.get("error_json")
        if isinstance(error_json, dict):
            error = error_json.get("detail") or error_json.get("error") or error_json
        else:
            error = error_json
        base["error"] = error
        base["artifact_id"] = artifact_id
        base["logs_url_hint"] = (
            f"call get_ft_training_logs(job_id={item.get('id')!r}) for full log text"
        )
        return base

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
                    "host. From Docker Open WebUI use "
                    "http://host.docker.internal:8000; same-host use "
                    "http://127.0.0.1:8000; remote use the LAN / Tailscale "
                    "address of the Mac."
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

    def delete_rag_collection(self, collection_id: str) -> str:
        """Delete a RAG collection and all of its documents. DESTRUCTIVE.

        Cascades: removes every document in the collection plus the
        on-disk storage directory. Always confirm the user's intent
        before calling — the cascade cannot be undone, and a deleted
        seed collection is not silently restored on the next API
        restart.

        :param collection_id: Collection id from list_rag_collections.
        :return: JSON string with a confirmation envelope
            (deleted=true, document_count, storage_deleted), or an
            error envelope when the collection does not exist.
        """
        encoded_id = urllib.parse.quote(collection_id, safe="")
        status, body = self._request("DELETE", f"/rag-collections/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="delete_rag_collection")
        result = body if isinstance(body, dict) else {"raw": body}
        return self._format(
            {
                "ok": True,
                "action": "delete_rag_collection",
                "collection_id": result.get("collection_id") or collection_id,
                "deleted": bool(result.get("deleted", True)),
                "document_count": result.get("document_count"),
                "storage_deleted": result.get("storage_deleted"),
            }
        )

    # ---- Selectable models --------------------------------------------

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
        model, optionally grounded in a RAG collection.

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

    # ---- Jobs ----------------------------------------------------------

    def get_job_status(self, job_id: str) -> str:
        """Fetch the current status of a platform job.

        Use this to poll a queued job (e.g. an FT training job) for
        completion. When status is "succeeded" the result_json field carries
        the job output. When status is "failed" the error field explains why.

        :param job_id: Job id from the response of the enqueue call.
        :return: JSON string describing the job (status, attempts, error,
            result_json, timestamps).
        """
        encoded_id = urllib.parse.quote(job_id, safe="")
        status, body = self._request("GET", f"/jobs/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="get_job_status")
        return self._format({"ok": True, "job": self._project_job(body)})

    def summarize_job_result(self, job_id: str) -> str:
        """Return a concise summary of a platform job result."""
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

    # ---- Fine-tuning lifecycle (read-only) -----------------------------

    def list_ft_datasets(self) -> str:
        """List fine-tuning datasets registered on the platform.

        Use this when the user asks "what FT datasets exist", "which fine-tuning
        datasets are available", or before drilling into versions. Returns a
        compact projection (dataset_id, name, description, version_count,
        created_at); nested versions/rows are omitted.

        :return: JSON string with the dataset list, or an error envelope.
        """
        status, body = self._request("GET", "/ft-datasets")
        if status != 200:
            return self._error(status, body, action="list_ft_datasets")
        datasets = (
            [self._project_ft_dataset(item) for item in body]
            if isinstance(body, list)
            else body
        )
        return self._format({"ok": True, "datasets": datasets})

    def list_ft_dataset_versions(self, dataset_id: str) -> str:
        """List versions for one fine-tuning dataset.

        Use this when the user asks "what versions does dataset X have" or
        before fetching a version summary. The platform's dataset detail
        endpoint embeds versions; this method extracts and projects them.

        :param dataset_id: Dataset id from list_ft_datasets.
        :return: JSON string with the version list, or an error envelope when
            the dataset does not exist.
        """
        encoded_id = urllib.parse.quote(dataset_id, safe="")
        status, body = self._request("GET", f"/ft-datasets/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="list_ft_dataset_versions")
        versions: list[Any] | Any = []
        if isinstance(body, dict):
            raw_versions = body.get("versions") or []
            if isinstance(raw_versions, list):
                versions = [self._project_ft_version(item) for item in raw_versions]
            else:
                versions = raw_versions
        return self._format(
            {"ok": True, "dataset_id": dataset_id, "versions": versions}
        )

    def get_ft_dataset_version_summary(self, version_id: str) -> str:
        """Fetch the row-count summary for one fine-tuning dataset version.

        Use this when the user asks "how many rows does version X have" or
        "what's the status of FT version X". Returns the platform's
        already-compact summary (status, row_count, splits, row_summary,
        timestamps) with no row payloads.

        :param version_id: Version id from list_ft_dataset_versions.
        :return: JSON string with the summary, or an error envelope when the
            version does not exist.
        """
        encoded_id = urllib.parse.quote(version_id, safe="")
        status, body = self._request(
            "GET", f"/ft-dataset-versions/{encoded_id}/summary"
        )
        if status != 200:
            return self._error(status, body, action="get_ft_dataset_version_summary")
        return self._format({"ok": True, "summary": body})

    def list_ft_training_jobs(self) -> str:
        """List fine-tuning training jobs.

        Use this when the user asks "what FT training jobs ran", "which
        trainers are queued", or before drilling into a specific job. Returns
        a compact projection (job_id, status, dataset_name, base_model,
        training_method, created_at, finished_at).

        :return: JSON string with the training job list, or an error envelope.
        """
        status, body = self._request("GET", "/ft-training-jobs")
        if status != 200:
            return self._error(status, body, action="list_ft_training_jobs")
        jobs = (
            [self._project_ft_training_job(item) for item in body]
            if isinstance(body, list)
            else body
        )
        return self._format({"ok": True, "jobs": jobs})

    def get_ft_training_job(self, job_id: str) -> str:
        """Fetch detail for one fine-tuning training job.

        Use this when the user asks "tell me about FT training job X" or
        wants the failure reason / produced artifact id. Returns the compact
        projection plus error, artifact_id, and a logs_url_hint pointing at
        get_ft_training_logs.

        :param job_id: Training job id from list_ft_training_jobs.
        :return: JSON string with the job detail, or an error envelope on 404.
        """
        encoded_id = urllib.parse.quote(job_id, safe="")
        status, body = self._request("GET", f"/ft-training-jobs/{encoded_id}")
        if status != 200:
            return self._error(status, body, action="get_ft_training_job")
        return self._format({"ok": True, "job": self._project_ft_training_job_detail(body)})

    def get_ft_training_logs(self, job_id: str) -> str:
        """Fetch training log text for one fine-tuning training job.

        Use this when the user asks "show me the FT training logs" or "why
        did training fail". The platform returns either a JSON envelope with a
        ``log_text`` field or raw text; both are normalized into
        ``{"ok": true, "logs": "..."}``.

        :param job_id: Training job id from list_ft_training_jobs.
        :return: JSON string with the log text, or an error envelope on 404.
        """
        encoded_id = urllib.parse.quote(job_id, safe="")
        status, body = self._request("GET", f"/ft-training-jobs/{encoded_id}/logs")
        if status != 200:
            return self._error(status, body, action="get_ft_training_logs")
        logs: Any
        if isinstance(body, dict):
            logs = body.get("log_text") or body.get("logs") or body.get("raw") or ""
        elif isinstance(body, str):
            logs = body
        else:
            logs = body
        return self._format({"ok": True, "job_id": job_id, "logs": logs})
