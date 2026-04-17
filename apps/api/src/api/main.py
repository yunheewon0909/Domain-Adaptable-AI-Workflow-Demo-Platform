from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from api.db import get_engine
from api.dependencies import get_embedding_client, get_llm_client
from api.routers.datasets import router as datasets_router
from api.routers.demo import router as demo_router
from api.routers.fine_tuning import router as fine_tuning_router
from api.routers.health import router as health_router
from api.routers.jobs import router as jobs_router
from api.routers.models import router as models_router
from api.routers.plc import router as plc_router
from api.routers.rag import router as rag_router
from api.routers.workflows import router as workflows_router
from api.services.datasets.registry import ensure_default_datasets
from api.services.model_registry import ensure_default_models
from api.services.starter_definitions import get_default_starter

_DEMO_STATIC_ROOT = Path(__file__).resolve().parent / "static" / "demo"


def create_app() -> FastAPI:
    active_starter = get_default_starter()
    app = FastAPI(title=active_starter.app.title, version=active_starter.app.version)
    app.state.starter = active_starter

    if active_starter.demo.enabled:
        app.mount(
            "/demo/assets", StaticFiles(directory=_DEMO_STATIC_ROOT), name="demo-assets"
        )

    app.include_router(health_router)
    app.include_router(datasets_router)
    app.include_router(workflows_router)
    app.include_router(jobs_router)
    app.include_router(fine_tuning_router)
    app.include_router(models_router)
    app.include_router(plc_router)
    app.include_router(rag_router)
    if active_starter.demo.enabled:
        app.include_router(demo_router)

    @app.on_event("startup")
    def startup() -> None:
        engine = get_engine()
        with Session(engine) as session:
            ensure_default_datasets(session)
            ensure_default_models(session)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
