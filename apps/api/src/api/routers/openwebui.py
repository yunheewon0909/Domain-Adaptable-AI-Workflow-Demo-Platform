from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["openwebui"])


_OPENWEBUI_STATIC_ROOT = (
    Path(__file__).resolve().parent.parent / "static" / "openwebui"
)
_PLATFORM_TOOLS_FILENAME = "platform_tools.py"


def _platform_tools_path() -> Path:
    return _OPENWEBUI_STATIC_ROOT / _PLATFORM_TOOLS_FILENAME


@router.get("/openwebui/platform_tools.py", response_class=PlainTextResponse)
def get_platform_tools_artifact() -> PlainTextResponse:
    """Serve the Open WebUI Tool source so a reviewer can install it by URL.

    Open WebUI's Workspace -> Tools admin accepts a pasted Python module that
    exposes a ``Tools`` class. This endpoint returns that module verbatim so
    reviewers can ``curl`` it or paste the link into Open WebUI without
    cloning the repo.
    """
    path = _platform_tools_path()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="platform tools artifact not found")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/x-python; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{_PLATFORM_TOOLS_FILENAME}"',
            "X-Open-WebUI-Tool": "platform_tools",
        },
    )


@router.get("/openwebui/manifest.json")
def get_openwebui_manifest() -> dict[str, object]:
    """Tiny manifest describing the Tool artifact this API serves.

    Useful for reviewers who want to discover what's available without
    reading the Python file first.
    """
    return {
        "tools": [
            {
                "id": "platform_tools",
                "title": "Domain Adaptable AI Platform - RAG & Workflows",
                "url_path": f"/openwebui/{_PLATFORM_TOOLS_FILENAME}",
                "methods": [
                    "list_rag_collections",
                    "query_rag_collection",
                    "list_workflows",
                    "enqueue_workflow_job",
                    "run_workflow_and_wait",
                    "get_job_status",
                ],
                "install_hint": (
                    "Open WebUI -> Workspace -> Tools -> + (New), paste the "
                    "served file's contents, save, then enable the tool on "
                    "a chat. Adjust the api_base_url Valve if Open WebUI is "
                    "not on the same Docker network as the platform API."
                ),
            }
        ],
    }
