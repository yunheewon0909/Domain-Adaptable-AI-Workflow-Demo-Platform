import asyncio
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
from api.routers.lmstudio import router as lmstudio_router
from api.routers.models import router as models_router
from api.routers.openai_compat import router as openai_compat_router
from api.routers.openwebui import router as openwebui_router
from api.routers.rag import router as rag_router
from api.services.background_runner import (
    reap_stale_running_jobs,
    reap_stale_training_jobs,
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


def _auto_load_lmstudio_chat_model() -> None:
    """Ensure an LLM is loaded in LM Studio at startup so inference works immediately.

    Algorithm:
    1. Run ``lms ls --json`` to discover locally indexed models.
    2. If ``LMSTUDIO_CHAT_MODEL`` is among the indexed LLMs, prefer it.
    3. Otherwise fall back to the smallest indexed LLM by ``sizeBytes``.
    4. If the chosen model is not already loaded, call ``lms load``.
    5. Update the "Default LM Studio model" registry row so its
       ``serving_model_name`` matches the identifier actually loaded into
       LM Studio (needed for /v1/chat/completions model resolution).
    """
    import json
    import shutil
    import subprocess
    from datetime import datetime, timezone

    from sqlalchemy import select
    from sqlalchemy.orm import Session as _Session

    from api.db import get_engine
    from api.models import ModelRegistryRecord
    from api.services.model_registry.lmstudio_register import (
        invalidate_loaded_cache,
        loaded_lmstudio_models,
    )

    settings = get_settings()
    base_url = settings.lmstudio_base_url
    configured_chat = (settings.lmstudio_chat_model or "").strip()

    # Resolve lms CLI (mirrors _resolve_lms_exe in lmstudio router)
    lms: str | None = shutil.which("lms")
    if lms is None:
        from pathlib import Path as _Path

        candidate = _Path.home() / ".lmstudio" / "bin" / "lms"
        lms = str(candidate) if candidate.is_file() else None
    if lms is None:
        logger.warning("auto_load: lms CLI not found; skipping model auto-load")
        return

    # Enumerate indexed models
    try:
        completed = subprocess.run(
            [lms, "ls", "--json"], capture_output=True, text=True, timeout=10
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("auto_load: lms ls failed: %s", exc)
        return
    if completed.returncode != 0:
        logger.warning(
            "auto_load: lms ls exit %d: %s",
            completed.returncode,
            completed.stderr.strip()[:200],
        )
        return
    try:
        listing = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("auto_load: lms ls non-JSON: %s", exc)
        return
    if not isinstance(listing, list):
        logger.warning("auto_load: lms ls returned unexpected shape")
        return

    indexed_llms = [
        e for e in listing if isinstance(e, dict) and e.get("type") == "llm"
    ]
    if not indexed_llms:
        logger.warning("auto_load: no LLM models indexed in LM Studio; skipping")
        return

    # Pick model: prefer configured if indexed, else smallest by sizeBytes
    target: dict | None = None
    if configured_chat:
        cfg_lower = configured_chat.lower()
        for entry in indexed_llms:
            candidates = {
                (entry.get("modelKey") or "").lower(),
                (entry.get("indexedModelIdentifier") or "").lower(),
            }
            if cfg_lower in candidates:
                target = entry
                break
    if target is None:
        target = min(indexed_llms, key=lambda e: e.get("sizeBytes") or float("inf"))
        logger.info(
            "auto_load: configured model %r not indexed; falling back to %r",
            configured_chat or "(unset)",
            target.get("modelKey"),
        )

    model_key = str(target.get("modelKey") or "")
    indexed_id = str(target.get("indexedModelIdentifier") or model_key)
    serving_name = indexed_id or model_key
    if not model_key:
        logger.warning("auto_load: selected model has no modelKey; aborting")
        return

    # Skip loading if the model is already live in LM Studio
    currently_loaded = loaded_lmstudio_models(base_url=base_url)
    candidate_ids = {s for s in (model_key, indexed_id) if s}
    if candidate_ids & set(currently_loaded):
        logger.info("auto_load: %r already loaded in LM Studio", serving_name)
    else:
        logger.info("auto_load: loading %r into LM Studio...", model_key)
        cmd = [lms, "load", model_key, "--gpu", "max", "--exact"]
        if indexed_id and indexed_id != model_key:
            cmd.extend(["--identifier", indexed_id])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("auto_load: lms load failed: %s", exc)
            return
        if result.returncode != 0:
            logger.warning(
                "auto_load: lms load exit %d: %s",
                result.returncode,
                result.stderr.strip()[:300],
            )
            return
        logger.info("auto_load: %r loaded successfully", serving_name)
        invalidate_loaded_cache()

    # Update "Default LM Studio model" registry row to the actual serving name
    with _Session(get_engine()) as db:
        default_row = db.scalar(
            select(ModelRegistryRecord).where(
                ModelRegistryRecord.source_type == "base",
                ModelRegistryRecord.display_name == "Default LM Studio model",
            )
        )
        if default_row is not None:
            if default_row.serving_model_name != serving_name:
                logger.info(
                    "auto_load: registry default row %r → %r",
                    default_row.serving_model_name,
                    serving_name,
                )
                default_row.serving_model_name = serving_name
                default_row.base_model_name = serving_name
                default_row.published_model_name = serving_name
                default_row.updated_at = datetime.now(timezone.utc)
            db.commit()
        else:
            logger.warning(
                "auto_load: 'Default LM Studio model' row not found; skipping registry update"
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
        stale_training = reap_stale_training_jobs(session)
        if stale_training:
            logger.info(
                "marked %d stale training jobs (mid-flight phase, no running backing job) as failed",
                stale_training,
            )
    await asyncio.to_thread(_auto_load_lmstudio_chat_model)
    await asyncio.to_thread(probe_lmstudio_health)
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
    app.include_router(lmstudio_router)
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
