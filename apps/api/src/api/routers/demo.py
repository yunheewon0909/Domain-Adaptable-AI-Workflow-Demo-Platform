from html import escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["demo"])

_DEMO_ROOT = Path(__file__).resolve().parent.parent / "static" / "demo"


@router.get("/demo")
def get_demo(request: Request) -> HTMLResponse:
    starter = request.app.state.starter
    html = (_DEMO_ROOT / "index.html").read_text(encoding="utf-8")
    rendered = (
        html.replace("{{APP_TITLE}}", escape(starter.app.title))
        .replace("{{DEMO_EYEBROW}}", escape(starter.demo.eyebrow))
        .replace("{{DEMO_SUBTITLE}}", escape(starter.demo.subtitle))
    )
    return HTMLResponse(rendered)
