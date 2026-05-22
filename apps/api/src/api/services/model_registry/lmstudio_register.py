"""Place fused MLX models into LM Studio's models directory.

LM Studio discovers models under `~/.lmstudio/models/<creator>/<repo>/` (or
the override directory configured in its Settings panel). Any directory with
`config.json` + `model.safetensors` + tokenizer files becomes loadable.

This module copies-or-symlinks a fused MLX bundle into that tree so reviewers
can load a freshly fine-tuned model in LM Studio with one click, then verifies
the model is actually loaded by probing LM Studio's `/v1/models` endpoint.

Auto-load is intentionally out of scope: LM Studio does not expose a public
local API to load a model on the user's behalf. The reviewer still flips the
toggle in LM Studio's UI. Once loaded, our probe sees it and the platform
registry row can transition from `artifact_ready` to `published`/selectable.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import shutil
import urllib.error
import urllib.request


logger = logging.getLogger("api.lmstudio_register")


@dataclass(frozen=True)
class RegisterResult:
    target_dir: Path | None
    used_symlinks: bool
    copied_file_count: int
    detail: str


def default_lmstudio_models_dir() -> Path:
    return Path.home() / ".lmstudio" / "models"


def register_fused_model(
    *,
    fused_model_dir: Path,
    lmstudio_models_dir: Path,
    namespace: str,
    model_name: str,
) -> RegisterResult:
    """Place a fused MLX model dir under lmstudio_models_dir/<namespace>/<model_name>.

    - if `fused_model_dir` does not exist or is empty, returns RegisterResult
      with target_dir=None
    - if `lmstudio_models_dir` does not exist, returns target_dir=None and a
      detail string explaining the user needs to install LM Studio or override
      LMSTUDIO_MODELS_DIR
    - otherwise, creates the namespaced subdirectory and symlinks each file
      from the fused model dir into it (falls back to copy on OSError, e.g.
      cross-filesystem mounts)
    """
    if not fused_model_dir.exists() or not any(fused_model_dir.iterdir()):
        return RegisterResult(
            target_dir=None,
            used_symlinks=False,
            copied_file_count=0,
            detail=f"fused model dir {fused_model_dir} is missing or empty",
        )
    if not lmstudio_models_dir.exists():
        return RegisterResult(
            target_dir=None,
            used_symlinks=False,
            copied_file_count=0,
            detail=(
                f"LM Studio models dir {lmstudio_models_dir} does not exist. "
                "Install LM Studio or set LMSTUDIO_MODELS_DIR to override."
            ),
        )

    safe_namespace = namespace.strip().strip("/") or "platform"
    safe_model_name = model_name.strip().strip("/") or "fine-tuned"
    target_dir = lmstudio_models_dir / safe_namespace / safe_model_name
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    used_symlinks = True
    for source in sorted(fused_model_dir.iterdir()):
        if source.is_dir():
            continue  # tokenizer assets are flat in MLX fused output
        destination = target_dir / source.name
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        try:
            destination.symlink_to(source.resolve())
        except OSError:
            used_symlinks = False
            shutil.copy2(source, destination)
        copied += 1

    return RegisterResult(
        target_dir=target_dir,
        used_symlinks=used_symlinks,
        copied_file_count=copied,
        detail=(
            f"placed {copied} file(s) under {target_dir} "
            f"({'symlinks' if used_symlinks else 'copies'})"
        ),
    )


def probe_lmstudio_for_model(*, base_url: str, model_id: str, timeout: float = 5.0) -> bool:
    """Return True if LM Studio's /v1/models endpoint lists `model_id`."""
    if not model_id:
        return False
    url = f"{base_url.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        logger.warning("LM Studio probe failed at %s: %s", url, exc)
        return False
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        logger.warning("LM Studio /models returned non-JSON: %s", exc)
        return False
    loaded = {
        str(item.get("id"))
        for item in parsed.get("data", [])
        if isinstance(item, dict) and item.get("id")
    }
    return model_id in loaded
