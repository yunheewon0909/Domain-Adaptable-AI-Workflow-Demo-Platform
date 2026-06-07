"""
title: Domain Adaptable AI Platform - Graph RAG & Evaluation
author: Domain Adaptable AI Platform
author_url: https://github.com/
funding_url: https://github.com/
version: 0.3.0
license: MIT
description: >
  Open WebUI Tool exposing the platform's Graph RAG and evaluation surface:
  manage collections, upload documents, search the knowledge graph, inspect
  entities/subgraphs, and generate + run evaluation testsets with reports.
  Connects to the FastAPI service at the configured base URL (defaults to
  http://api:8000 inside Docker Compose; use http://host.docker.internal:8000
  for a native runtime, or http://127.0.0.1:8000 on the same host).

This file is designed to be installed into Open WebUI as a Tool:

  Open WebUI -> Workspace -> Tools -> + (New)
  paste this entire file, set the Valves if needed, then enable the tool on a
  chat. The chat model can then call these methods through Open WebUI's tool
  calling. Only the Python standard library + pydantic are used so the tool
  runs inside any Open WebUI container without extra packages.
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
    return JSON-encoded strings so the calling model can read them directly.
    """

    class Valves(BaseModel):
        api_base_url: str = Field(
            default=_DEFAULT_BASE_URL,
            description=(
                "Base URL of the platform FastAPI service. Default targets the "
                "`api` service inside Docker Compose; use "
                "http://host.docker.internal:8000 for a native runtime or "
                "http://127.0.0.1:8000 on the same host."
            ),
        )
        request_timeout_seconds: int = Field(
            default=_DEFAULT_TIMEOUT_SECONDS,
            ge=1,
            le=300,
            description="HTTP timeout for every call into the platform API.",
        )
        default_top_k: int = Field(
            default=5,
            ge=1,
            le=20,
            description="Default top_k used for searches when the chat does not specify one.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    # ---- helpers -------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.valves.api_base_url.rstrip('/')}{path}"

    def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        url = self._url(path)
        data: bytes | None = None
        headers = {"Accept": "application/json"}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method not in ("GET", "POST", "DELETE", "PATCH"):
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

    def _error(self, status: int, body: Any, *, action: str) -> str:
        return self._format(
            {
                "ok": False,
                "action": action,
                "http_status": status,
                "platform_response": body,
                "hint": (
                    "Check that api_base_url is reachable from the Open WebUI "
                    "container and that the platform API is running."
                ),
            }
        )

    def _ok(self, status: int, body: Any, *, action: str, **extra: Any) -> str:
        if status < 200 or status >= 300:
            return self._error(status, body, action=action)
        return self._format({"ok": True, **extra, "result": body})

    # ---- collections ---------------------------------------------------

    def list_collections(self) -> str:
        """List RAG collections (knowledge bases) on the platform.

        :return: JSON string with the collection list, or an error envelope.
        """
        status, body = self._request("GET", "/rag-collections")
        if status != 200:
            return self._error(status, body, action="list_collections")
        collections = (
            [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "description": c.get("description"),
                    "document_count": c.get("document_count"),
                    "index_status": c.get("index_status"),
                }
                for c in body
                if isinstance(c, dict)
            ]
            if isinstance(body, list)
            else body
        )
        return self._format({"ok": True, "collections": collections})

    def create_collection(self, name: str, description: str | None = None) -> str:
        """Create a new RAG collection (knowledge base).

        :param name: Human-readable collection name.
        :param description: Optional description.
        :return: JSON string with the created collection, or an error envelope.
        """
        payload: dict[str, Any] = {"name": name}
        if description is not None:
            payload["description"] = description
        status, body = self._request("POST", "/rag-collections", json_body=payload)
        return self._ok(status, body, action="create_collection")

    def upload_text_document(
        self, collection_id: str, filename: str, content: str
    ) -> str:
        """Add a text document to a collection.

        :param collection_id: Target collection id.
        :param filename: Display filename for the document.
        :param content: Plain-text document body.
        :return: JSON string with the created document, or an error envelope.
        """
        encoded = urllib.parse.quote(collection_id, safe="")
        status, body = self._request(
            "POST",
            f"/rag-collections/{encoded}/documents/text",
            json_body={"filename": filename, "content": content},
        )
        return self._ok(status, body, action="upload_text_document")

    # ---- graph search + inspection ------------------------------------

    def search_collection(
        self,
        collection_id: str,
        query: str,
        mode: str = "local",
        top_k: int | None = None,
    ) -> str:
        """Search a collection with Graph RAG retrieval.

        :param collection_id: Collection to search.
        :param query: Natural-language query.
        :param mode: "local" (graph neighborhood), "global" (community
            summaries), or "naive" (chunk vectors). Defaults to local.
        :param top_k: Optional result count (clamped server-side).
        :return: JSON string with retrieval evidence (chunks, entities,
            relationships, communities, context) + a trace id, or an error.
        """
        encoded = urllib.parse.quote(collection_id, safe="")
        payload: dict[str, Any] = {
            "query": query,
            "mode": mode,
            "top_k": top_k if top_k is not None else self.valves.default_top_k,
        }
        status, body = self._request(
            "POST", f"/rag-collections/{encoded}/query", json_body=payload
        )
        return self._ok(status, body, action="search_collection")

    def get_entity(self, entity_id: str) -> str:
        """Fetch one knowledge-graph entity and its relationships.

        :param entity_id: Entity id (from search_collection or get_subgraph).
        :return: JSON string with the entity + relationships, or an error.
        """
        encoded = urllib.parse.quote(entity_id, safe="")
        status, body = self._request("GET", f"/rag-entities/{encoded}")
        return self._ok(status, body, action="get_entity")

    def get_subgraph(self, collection_id: str, limit: int | None = None) -> str:
        """Fetch the collection's knowledge graph (top entities + edges).

        :param collection_id: Collection id.
        :param limit: Max number of entities (by degree). Server clamps 1..1000.
        :return: JSON string with nodes + edges, or an error envelope.
        """
        encoded = urllib.parse.quote(collection_id, safe="")
        path = f"/rag-collections/{encoded}/subgraph"
        if limit is not None:
            path += f"?limit={int(limit)}"
        status, body = self._request("GET", path)
        return self._ok(status, body, action="get_subgraph")

    # ---- evaluation ----------------------------------------------------

    def generate_evaluation_set(
        self,
        collection_id: str,
        name: str,
        questions_per_chunk: int | None = None,
    ) -> str:
        """Generate a reviewable evaluation testset from a collection's chunks.

        :param collection_id: Collection to derive questions from (must be indexed).
        :param name: Name for the evaluation set.
        :param questions_per_chunk: Optional questions per chunk (1..10).
        :return: JSON string with the created evaluation set, or an error.
        """
        payload: dict[str, Any] = {"collection_id": collection_id, "name": name}
        if questions_per_chunk is not None:
            payload["questions_per_chunk"] = int(questions_per_chunk)
        status, body = self._request(
            "POST", "/evaluation-sets/from-collection", json_body=payload
        )
        return self._ok(status, body, action="generate_evaluation_set")

    def run_rag_evaluation(
        self, evaluation_set_id: str, mode: str = "local"
    ) -> str:
        """Enqueue a RAG evaluation run over an evaluation set.

        :param evaluation_set_id: Set to evaluate.
        :param mode: Retrieval mode (local/global/naive).
        :return: JSON string with the queued run + backing job, or an error.
            Poll get_job_status, then fetch get_evaluation_report.
        """
        status, body = self._request(
            "POST",
            "/evaluation-runs",
            json_body={"evaluation_set_id": evaluation_set_id, "mode": mode},
        )
        return self._ok(status, body, action="run_rag_evaluation")

    def get_evaluation_report(self, run_id: str) -> str:
        """Fetch the report + per-question results for an evaluation run.

        :param run_id: Evaluation run id from run_rag_evaluation.
        :return: JSON string with the report (answer quality, retrieval quality,
            collection health) + per-question results, or an error envelope.
        """
        encoded = urllib.parse.quote(run_id, safe="")
        status, body = self._request("GET", f"/evaluation-runs/{encoded}/report")
        return self._ok(status, body, action="get_evaluation_report")

    # ---- jobs ----------------------------------------------------------

    def get_job_status(self, job_id: str) -> str:
        """Poll a queued platform job (indexing or evaluation).

        :param job_id: Job id returned by an enqueue call.
        :return: JSON string describing the job, or an error envelope.
        """
        encoded = urllib.parse.quote(job_id, safe="")
        status, body = self._request("GET", f"/jobs/{encoded}")
        return self._ok(status, body, action="get_job_status")
