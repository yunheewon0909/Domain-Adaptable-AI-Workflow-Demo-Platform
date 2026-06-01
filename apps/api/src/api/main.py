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

    # Pick model: prefer configured if indexed, else smallest by sizeBytes.
    # Track whether the configured model was actually found so we don't
    # overwrite the registry default row with an unrelated fallback model.
    # Fine-tuned (published) models must never be selected as the fallback
    # base model — they share the LM Studio namespace but represent
    # registry-owned FT artifacts, and writing them into the "Default LM
    # Studio model" base row creates a collision with the actual FT row.
    target: dict | None = None
    used_configured = False
    if configured_chat:
        cfg_lower = configured_chat.lower()
        for entry in indexed_llms:
            candidates = {
                (entry.get("modelKey") or "").lower(),
                (entry.get("indexedModelIdentifier") or "").lower(),
            }
            if cfg_lower in candidates:
                target = entry
                used_configured = True
                break

    if target is None:
        # Collect every FT serving/published name from the registry so we can
        # filter them out of the smallest-model fallback.  Without this, an
        # FT model can be the smallest LLM and get picked as the platform
        # default — overwriting the "Default LM Studio model" row with an FT
        # name that then collides with the actual FT row in /v1/models.
        ft_blocklist: set[str] = set()
        try:
            with _Session(get_engine()) as _db:
                for _row in _db.scalars(
                    select(ModelRegistryRecord).where(
                        ModelRegistryRecord.source_type == "fine_tuned"
                    )
                ):
                    for _name in (_row.serving_model_name, _row.published_model_name):
                        if _name:
                            ft_blocklist.add(_name.lower())
                            base = _name.lower().rsplit("/", 1)[-1]
                            ft_blocklist.add(base)
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto_load: could not load FT blocklist: %s", exc)

        eligible_base = [
            e for e in indexed_llms
            if (e.get("modelKey") or "").lower() not in ft_blocklist
            and (e.get("indexedModelIdentifier") or "").lower() not in ft_blocklist
            and (e.get("modelKey") or "").lower().rsplit("/", 1)[-1] not in ft_blocklist
        ]
        if not eligible_base:
            logger.warning(
                "auto_load: no non-FT base models indexed in LM Studio; skipping fallback"
            )
            return
        target = min(eligible_base, key=lambda e: e.get("sizeBytes") or float("inf"))
        logger.info(
            "auto_load: configured model %r not indexed; falling back to %r",
            configured_chat or "(unset)",
            target.get("modelKey"),
        )

    model_key = str(target.get("modelKey") or "")
    indexed_id = str(target.get("indexedModelIdentifier") or model_key)
    # Use modelKey (not indexedModelIdentifier) as the serving name because
    # LM Studio's /v1/models endpoint exposes loaded models by their modelKey,
    # not by their namespaced indexedModelIdentifier.  Using indexed_id would
    # produce serving_model_name values like "demo/foo" that the readiness
    # probe can't match against the /v1/models response.
    serving_name = model_key
    if not model_key:
        logger.warning("auto_load: selected model has no modelKey; aborting")
        return

    # Skip loading if the model is already live in LM Studio
    currently_loaded = loaded_lmstudio_models(base_url=base_url)
    candidate_ids = {s.lower() for s in (model_key, indexed_id) if s}
    loaded_lower = {s.lower() for s in currently_loaded}
    if candidate_ids & loaded_lower:
        logger.info("auto_load: %r already loaded in LM Studio", serving_name)
    else:
        logger.info("auto_load: loading %r into LM Studio...", model_key)
        cmd = [lms, "load", model_key, "--gpu", "max", "--exact"]
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

    # Only update the registry's "Default LM Studio model" row when the
    # OPERATOR-CONFIGURED LMSTUDIO_CHAT_MODEL was indexed and we just loaded
    # it.  In every other case — model was unset, or the configured one
    # wasn't found and we fell back to the smallest LLM — leave the registry
    # untouched.  The fallback is a runtime convenience (so the API has *a*
    # model usable through the shim), not a config change.  Writing the
    # fallback name into the registry can corrupt the default row (e.g. by
    # pointing it at an FT model name) and conflict with real FT rows.
    if not used_configured:
        if configured_chat:
            logger.info(
                "auto_load: skipping registry update (fallback %r ≠ configured %r)",
                serving_name,
                configured_chat,
            )
        else:
            logger.info(
                "auto_load: skipping registry update (no LMSTUDIO_CHAT_MODEL configured)"
            )
        return

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
    # Run LM Studio setup in the background so the API becomes ready
    # immediately. `lms load` can take minutes; we don't want the server
    # to be unreachable during that time. The probe + auto-load only
    # log warnings / mutate the registry — they are safe to defer.
    async def _bg_lmstudio_setup() -> None:
        try:
            await asyncio.to_thread(_auto_load_lmstudio_chat_model)
        except Exception as exc:  # noqa: BLE001 — best-effort startup task
            logger.warning("auto_load: background task crashed: %s", exc)
        try:
            await asyncio.to_thread(probe_lmstudio_health)
        except Exception as exc:  # noqa: BLE001
            logger.warning("probe_lmstudio_health: background task crashed: %s", exc)

    bg_setup_task = asyncio.create_task(_bg_lmstudio_setup())
    dispatcher_task, dispatcher_stop = start_dispatcher_task()
    try:
        yield
    finally:
        if not bg_setup_task.done():
            bg_setup_task.cancel()
            try:
                await bg_setup_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
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
