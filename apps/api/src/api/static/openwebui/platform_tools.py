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
        return self._format({"ok": True, "collections": body})

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
        return self._format({"ok": True, "retrieval": body})

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
        return self._format({"ok": True, "workflows": body})

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
        return self._format(
            {
                "ok": True,
                "job": body,
                "next_step": (
                    "Call get_job_status with this job_id to poll until the "
                    "status is 'succeeded' or 'failed'."
                ),
            }
        )

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
        return self._format({"ok": True, "job": body})
