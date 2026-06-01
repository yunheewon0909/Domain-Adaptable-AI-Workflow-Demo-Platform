"""Demo-facing LM Studio control surface.

Exposes:
- GET /lmstudio/models — full `lms ls --json` listing (loaded + unloaded)
- POST /lmstudio/models/load — invoke `lms load <id>` so the demo can
  auto-load a model the reviewer selects from the dropdown

Kept narrow on purpose: this is reviewer convenience, not a general
LM Studio remote control surface. Both endpoints shell out to the
`lms` CLI at `~/.lmstudio/bin/lms` (the canonical install location
for LM Studio's CLI helper).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field


router = APIRouter(tags=["lmstudio"])


def _resolve_lms_exe() -> str | None:
    found = shutil.which("lms")
    if found:
        return found
    default = Path.home() / ".lmstudio" / "bin" / "lms"
    return str(default) if default.is_file() else None


@router.get("/lmstudio/models")
def get_lmstudio_models() -> dict[str, Any]:
    """Return all LLMs LM Studio has indexed locally (loaded + unloaded)."""
    lms = _resolve_lms_exe()
    if lms is None:
        raise HTTPException(
            status_code=503,
            detail="lms CLI not found; install LM Studio's CLI or set PATH",
        )
    try:
        completed = subprocess.run(
            [lms, "ls", "--json"], capture_output=True, text=True, timeout=10
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"lms ls failed: {exc}") from exc
    if completed.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=f"lms ls exit {completed.returncode}: {completed.stderr.strip()[:300]}",
        )
    try:
        listing = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail=f"lms ls returned non-JSON: {exc}"
        ) from exc
    if not isinstance(listing, list):
        raise HTTPException(status_code=502, detail="lms ls returned unexpected shape")

    # `lms ls --json` always reports `deviceIdentifier=null` regardless of
    # whether the model is loaded. The reliable source for "currently
    # loaded" is LM Studio's own /v1/models endpoint — anything listed
    # there is loaded right now.
    from api.config import get_settings
    from api.services.model_registry.lmstudio_register import loaded_lmstudio_models

    settings = get_settings()
    try:
        loaded = loaded_lmstudio_models(base_url=settings.lmstudio_base_url)
    except Exception:
        loaded = frozenset()

    models: list[dict[str, Any]] = []
    for entry in listing:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") not in {"llm", "embedding"}:
            continue
        candidates = {
            str(entry.get(field) or "")
            for field in ("modelKey", "indexedModelIdentifier", "path")
        }
        is_loaded = any(c and c in loaded for c in candidates)
        models.append(
            {
                "modelKey": entry.get("modelKey"),
                "indexedModelIdentifier": entry.get("indexedModelIdentifier"),
                "path": entry.get("path"),
                "type": entry.get("type"),
                "displayName": entry.get("displayName"),
                "publisher": entry.get("publisher"),
                "architecture": entry.get("architecture"),
                "sizeBytes": entry.get("sizeBytes"),
                "maxContextLength": entry.get("maxContextLength"),
                "loaded": is_loaded,
            }
        )
    return {"models": models}


class LoadModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, description="modelKey or indexedModelIdentifier")
    identifier: str | None = Field(
        default=None,
        description=(
            "Optional `--identifier` for `lms load`; defaults to the path so the "
            "loaded model appears in /v1/models under its namespaced id."
        ),
    )


@router.post("/lmstudio/models/load")
def post_lmstudio_load(request: LoadModelRequest) -> dict[str, Any]:
    lms = _resolve_lms_exe()
    if lms is None:
        raise HTTPException(status_code=503, detail="lms CLI not found")

    # Resolve aliases to the stable modelKey when possible. On this Mac,
    # `lms load demo/<IndexedIdentifier> --exact` can open an interactive
    # selector and hang; the non-interactive path is the lowercase modelKey.
    load_target = request.model_id
    try:
        listing_result = subprocess.run(
            [lms, "ls", "--json"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL
        )
        if listing_result.returncode == 0:
            try:
                listing = json.loads(listing_result.stdout)
            except json.JSONDecodeError:
                listing = []
            if isinstance(listing, list):
                for entry in listing:
                    if not isinstance(entry, dict):
                        continue
                    candidates = {
                        str(entry.get(field) or "")
                        for field in ("modelKey", "indexedModelIdentifier", "path")
                    }
                    if request.model_id in candidates:
                        load_target = (
                            str(entry.get("modelKey") or "")
                            or str(entry.get("path") or "")
                            or request.model_id
                        )
                        break
    except (subprocess.TimeoutExpired, OSError):
        pass  # keep original model_id as fallback

    cmd = [lms, "load", load_target, "--gpu", "max"]
    resolved_identifier = request.identifier or load_target
    cmd.extend(["--identifier", resolved_identifier])
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise HTTPException(status_code=504, detail=f"lms load timed out: {exc}") from exc
    if completed.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=f"lms load exit {completed.returncode}: {completed.stderr.strip()[:300]}",
        )
    # Drop the LM Studio probe cache so the next /v1/models reflects the
    # freshly loaded model immediately rather than waiting 30s.  Also clear
    # the resolve cache in routers.models, otherwise the case-insensitive
    # lookup that runs inside the chat path could return a stale "not loaded"
    # result for up to 30 seconds after a fresh load (manifesting as HTTP 400
    # "Model not found").
    from api.services.model_registry.lmstudio_register import invalidate_loaded_cache
    from api.routers.models import invalidate_resolve_cache

    invalidate_loaded_cache()
    invalidate_resolve_cache()

    # Auto-register the loaded model in the platform registry as a base
    # row so /v1/chat/completions can resolve it via the shim. Without
    # this, reviewers can load a model from the demo dropdown but the
    # platform shim still rejects chat requests with "model not found in
    # registry".
    serving_name = resolved_identifier or load_target
    _ensure_base_model_registered(serving_name)

    return {
        "model_id": request.model_id,
        "identifier": resolved_identifier,
        "serving_model_name": serving_name,
        "loaded": True,
        "stdout_tail": completed.stdout.strip()[-300:],
    }


def _ensure_base_model_registered(serving_model_name: str) -> None:
    """Idempotent: insert a `source_type=base` registry row for this
    serving_model_name if none exists yet. Lets the demo chat shim
    accept models the reviewer loads after startup."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select
    from sqlalchemy.orm import Session as _Session

    from api.db import get_engine
    from api.models import ModelRegistryRecord
    from api.services.model_registry.service import _next_prefixed_id

    if not serving_model_name.strip():
        return
    with _Session(get_engine()) as session:
        # Match case-insensitively against ANY existing row (base or
        # fine_tuned).  The load endpoint resolves load_target to LM Studio's
        # lowercased modelKey, while fine-tuned rows preserve the publish
        # manifest's mixed-case serving name (e.g. "demo/MyModel_2026-...").
        # A case-sensitive equality here would miss the FT row and insert a
        # duplicate source_type=base row pointing at the same loaded model.
        existing = session.scalar(
            select(ModelRegistryRecord).where(
                func.lower(ModelRegistryRecord.serving_model_name)
                == serving_model_name.lower()
            )
        )
        if existing is not None:
            return
        now = datetime.now(timezone.utc)
        session.add(
            ModelRegistryRecord(
                id=_next_prefixed_id("model"),
                display_name=serving_model_name,
                source_type="base",
                base_model_name=serving_model_name,
                serving_model_name=serving_model_name,
                published_model_name=serving_model_name,
                status="active",
                publish_status="published",
                tags_json=["base"],
                description=f"Loaded via LM Studio dropdown ({serving_model_name}).",
                updated_at=now,
            )
        )
        session.commit()
