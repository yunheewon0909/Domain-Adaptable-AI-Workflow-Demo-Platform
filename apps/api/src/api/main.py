from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from api.config import get_settings
from api.db import get_engine
from api.routers.demo import router as demo_router
from api.routers.fine_tuning import router as fine_tuning_router
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
from api.services.model_registry import ensure_default_models
from api.services.rag.collections import ensure_default_rag_collections
from api.services.starter_definitions import get_default_starter

_DEMO_STATIC_ROOT = Path(__file__).resolve().parent / "static" / "demo"

logger = logging.getLogger("api.startup")


def probe_lmstudio_health() -> None:
    """Best-effort probe at startup.

    Warns (does not fail) when LM Studio is unreachable or the configured chat
    model is not loaded. The platform still boots so reviewers can manage
    datasets and inspect history without LM Studio running.
    """
    settings = get_settings()
    base_url = settings.lmstudio_base_url.rstrip("/")
    configured_chat = (settings.lmstudio_chat_model or "").strip()
    configured_embed = (settings.lmstudio_embed_model or "").strip()
    if not configured_chat:
        logger.warning(
            "LMSTUDIO_CHAT_MODEL is not set; default model row will not be seeded."
        )
    try:
        response = httpx.get(f"{base_url}/models", timeout=5.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "LM Studio probe failed at %s/models: %s. Inference/RAG calls will fail until LM Studio is reachable.",
            base_url,
            exc,
        )
        return

    try:
        loaded_ids = [
            str(item.get("id"))
            for item in response.json().get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
    except ValueError as exc:
        logger.warning("LM Studio /models returned non-JSON payload: %s", exc)
        return

    for label, model_id in (("chat", configured_chat), ("embed", configured_embed)):
        if model_id and model_id not in loaded_ids:
            logger.warning(
                "Configured LMSTUDIO_%s_MODEL=%r is not loaded in LM Studio. Loaded models: %s",
                label.upper(),
                model_id,
                loaded_ids,
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    with Session(engine) as session:
        ensure_default_models(session)
        ensure_default_rag_collections(session)
        reaped = reap_unsupported_queue_rows(session)
        if reaped:
            logger.info(
                "marked %d queued/running jobs with deprecated types as failed",
                reaped,
            )
        stale_running = reap_stale_running_jobs(session)
        if stale_running:
            logger.info(
                "marked %d stale running jobs (left over from a previous process) as failed",
                stale_running,
            )
    probe_lmstudio_health()
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
    app.include_router(fine_tuning_router)
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
