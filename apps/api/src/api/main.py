import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from api.db import get_engine
from api.routers.demo import router as demo_router
from api.routers.health import router as health_router
from api.routers.jobs import router as jobs_router
from api.routers.models import router as models_router
from api.routers.openai_compat import router as openai_compat_router
from api.routers.openwebui import router as openwebui_router
from api.routers.rag import router as rag_router
from api.services.background_runner import (
    reap_stale_running_jobs,
    reap_unsupported_queue_rows,
    start_dispatcher_task,
    stop_dispatcher_task,
)
from api.services.rag.collections import ensure_default_rag_collections
from api.services.starter_definitions import get_default_starter

_DEMO_STATIC_ROOT = Path(__file__).resolve().parent / "static" / "demo"

logger = logging.getLogger("api.startup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    with Session(engine) as session:
        ensure_default_rag_collections(session)
        reaped = reap_unsupported_queue_rows(session)
        if reaped:
            logger.info(
                "marked %d queued/running jobs with deprecated types as failed", reaped
            )
        stale_running = reap_stale_running_jobs(session)
        if stale_running:
            logger.info(
                "marked %d stale running jobs (left over from a previous process) as failed",
                stale_running,
            )

    # In compose the worker container runs the dispatcher; the API runs with
    # FT_BACKGROUND_DISPATCH=false. For single-process local dev the API can run
    # the loop itself by setting it true.
    dispatcher_task, dispatcher_stop = start_dispatcher_task()
    try:
        yield
    finally:
        await stop_dispatcher_task(dispatcher_task, dispatcher_stop)


def create_app() -> FastAPI:
    active_starter = get_default_starter()
    app = FastAPI(
        title=active_starter.app.title,
        version=active_starter.app.version,
        lifespan=lifespan,
    )
    app.state.starter = active_starter

    if active_starter.demo.enabled:
        app.mount(
            "/demo/assets", StaticFiles(directory=_DEMO_STATIC_ROOT), name="demo-assets"
        )

    app.include_router(health_router)
    app.include_router(jobs_router)
    app.include_router(models_router)
    app.include_router(rag_router)
    app.include_router(openai_compat_router)
    app.include_router(openwebui_router)
    if active_starter.demo.enabled:
        app.include_router(demo_router)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
