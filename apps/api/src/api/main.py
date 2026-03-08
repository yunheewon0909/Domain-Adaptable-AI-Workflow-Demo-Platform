from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from api.db import get_engine
from api.dependencies import get_embedding_client, get_llm_client
from api.routers.datasets import router as datasets_router
from api.routers.demo import router as demo_router
from api.routers.health import router as health_router
from api.routers.jobs import router as jobs_router
from api.routers.rag import router as rag_router
from api.routers.workflows import router as workflows_router
from api.services.datasets.registry import ensure_default_datasets

app = FastAPI(title="Domain-Adaptable AI Workflow Demo API", version="0.1.0")

_DEMO_STATIC_ROOT = Path(__file__).resolve().parent / "static" / "demo"
app.mount("/demo/assets", StaticFiles(directory=_DEMO_STATIC_ROOT), name="demo-assets")

app.include_router(health_router)
app.include_router(datasets_router)
app.include_router(workflows_router)
app.include_router(jobs_router)
app.include_router(rag_router)
app.include_router(demo_router)


@app.on_event("startup")
def startup() -> None:
    engine = get_engine()
    with Session(engine) as session:
        ensure_default_datasets(session)


def run() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
