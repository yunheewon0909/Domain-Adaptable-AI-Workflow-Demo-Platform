from html import escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["demo"])

_DEMO_ROOT = Path(__file__).resolve().parent.parent / "static" / "demo"


ADMIN_EYEBROW = "Internal admin console (preferred)"
ADMIN_SUBTITLE = (
    "Internal reviewer/admin console for workflow, PLC, fine-tuning, model registry, "
    "and RAG operations. External chat UX is now expected to go through Open WebUI "
    "against the /v1/* OpenAI-compatible shim; this console stays the authoritative "
    "operator surface."
)


def _render_console(
    request: Request,
    *,
    eyebrow: str | None = None,
    subtitle: str | None = None,
) -> HTMLResponse:
    starter = request.app.state.starter
    html = (_DEMO_ROOT / "index.html").read_text(encoding="utf-8")
    rendered = (
        html.replace("{{APP_TITLE}}", escape(starter.app.title))
        .replace("{{DEMO_EYEBROW}}", escape(eyebrow or starter.demo.eyebrow))
        .replace("{{DEMO_SUBTITLE}}", escape(subtitle or starter.demo.subtitle))
    )
    return HTMLResponse(rendered)


@router.get("/demo")
def get_demo(request: Request) -> HTMLResponse:
    return _render_console(request)


@router.get("/admin")
def get_admin(request: Request) -> HTMLResponse:
    return _render_console(
        request,
        eyebrow=ADMIN_EYEBROW,
        subtitle=ADMIN_SUBTITLE,
    )
