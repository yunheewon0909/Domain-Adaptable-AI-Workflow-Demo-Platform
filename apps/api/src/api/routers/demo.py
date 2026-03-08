from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["demo"])

_DEMO_ROOT = Path(__file__).resolve().parent.parent / "static" / "demo"


@router.get("/demo")
def get_demo() -> FileResponse:
    return FileResponse(_DEMO_ROOT / "index.html")
