from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request


EXPECTED_CLI_TOOLS = ("mlx_lm.lora", "mlx_lm.fuse")
EXPECTED_TINY_MODEL = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
SUPPORTED_TRAINER_BACKENDS = {"mlx_qlora"}
SUPPORTED_TRAINING_METHODS = {"sft_qlora"}


@dataclass(frozen=True)
class CheckResult:
    level: str
    summary: str
    detail: str


@dataclass(frozen=True)
class PackageStatus:
    name: str
    available: bool
    detail: str = ""


@dataclass(frozen=True)
class DeviceStatus:
    mlx_available: bool
    metal_available: bool
    detail: str = ""


@dataclass(frozen=True)
class LMStudioStatus:
    reachable: bool
    loaded_models: tuple[str, ...]
    chat_model_loaded: bool
    embed_model_loaded: bool
    detail: str = ""


@dataclass(frozen=True)
class PreflightConfig:
    api_base_url: str
    artifact_dir: Path
    trainer_backend: str
    default_training_method: str
    trainer_model_map_json: str
    project_root: Path
    lmstudio_base_url: str
    lmstudio_chat_model: str
    lmstudio_embed_model: str


def _find_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "apps").exists() and (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def load_config() -> PreflightConfig:
    project_root = _find_project_root()
    artifact_dir_raw = os.getenv("MODEL_ARTIFACT_DIR", "data/model_artifacts")
    artifact_dir = Path(artifact_dir_raw)
    if not artifact_dir.is_absolute():
        artifact_dir = project_root / artifact_dir
    return PreflightConfig(
        api_base_url=os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        artifact_dir=artifact_dir,
        trainer_backend=os.getenv("FT_TRAINER_BACKEND", "mlx_qlora").strip()
        or "mlx_qlora",
        default_training_method=os.getenv(
            "FT_DEFAULT_TRAINING_METHOD", "sft_qlora"
        ).strip()
        or "sft_qlora",
        trainer_model_map_json=os.getenv("FT_TRAINER_MODEL_MAP_JSON", "{}"),
        project_root=project_root,
        lmstudio_base_url=os.getenv(
            "LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"
        ).rstrip("/"),
        lmstudio_chat_model=os.getenv("LMSTUDIO_CHAT_MODEL", "").strip(),
        lmstudio_embed_model=os.getenv("LMSTUDIO_EMBED_MODEL", "").strip(),
    )


def check_api_health(api_base_url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"{api_base_url}/health", timeout=5) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return (
                response.status == 200,
                payload.strip() or "health endpoint returned 200",
            )
    except urllib.error.URLError as exc:
        return False, str(exc)


def inspect_lmstudio(
    base_url: str, *, chat_model: str, embed_model: str
) -> LMStudioStatus:
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=5) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return LMStudioStatus(
            reachable=False,
            loaded_models=(),
            chat_model_loaded=False,
            embed_model_loaded=False,
            detail=f"unreachable at {base_url}/models: {exc}",
        )
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        return LMStudioStatus(
            reachable=False,
            loaded_models=(),
            chat_model_loaded=False,
            embed_model_loaded=False,
            detail=f"non-JSON response: {exc}",
        )
    loaded = tuple(
        str(item.get("id"))
        for item in parsed.get("data", [])
        if isinstance(item, dict) and item.get("id")
    )
    return LMStudioStatus(
        reachable=True,
        loaded_models=loaded,
        chat_model_loaded=bool(chat_model and chat_model in loaded),
        embed_model_loaded=bool(embed_model and embed_model in loaded),
        detail=f"{len(loaded)} model(s) loaded: {', '.join(loaded) or '<none>'}",
    )


def _run_subprocess(
    cmd: list[str], *, timeout: int
) -> tuple[int | None, str, str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "", f"command timed out after {timeout}s"
    except FileNotFoundError as exc:
        return None, "", str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def inspect_dependencies() -> list[PackageStatus]:
    tools: list[PackageStatus] = []
    for name in EXPECTED_CLI_TOOLS:
        path = shutil.which(name)
        if path is None:
            tools.append(
                PackageStatus(
                    name=name,
                    available=False,
                    detail="not found on PATH; install with `brew install mlx-lm`",
                )
            )
            continue
        returncode, stdout, stderr = _run_subprocess([path, "--help"], timeout=20)
        if returncode is None:
            tools.append(
                PackageStatus(name=name, available=False, detail=stderr)
            )
            continue
        tools.append(
            PackageStatus(
                name=name,
                available=returncode == 0,
                detail=(
                    f"{path} --help ok"
                    if returncode == 0
                    else (stderr.strip() or stdout.strip())
                ),
            )
        )
    return tools


def inspect_mlx_runtime() -> DeviceStatus:
    python_exe = shutil.which("python3.14") or shutil.which("python3")
    if python_exe is None:
        return DeviceStatus(
            mlx_available=False,
            metal_available=False,
            detail="python3.14/python3 not found on PATH",
        )
    returncode, stdout, stderr = _run_subprocess(
        [
            python_exe,
            "-c",
            (
                "import mlx.core as mx; "
                "print('metal=' + str(bool(mx.metal.is_available())).lower())"
            ),
        ],
        timeout=20,
    )
    if returncode is None or returncode != 0:
        return DeviceStatus(
            mlx_available=False,
            metal_available=False,
            detail=stderr.strip() or stdout.strip(),
        )
    metal_available = "metal=true" in stdout.strip().lower()
    return DeviceStatus(
        mlx_available=True,
        metal_available=metal_available,
        detail=f"{python_exe}: {stdout.strip()}",
    )


def check_artifact_dir(artifact_dir: Path) -> tuple[bool, str]:
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        probe = artifact_dir / ".ft-smoke-preflight-write-check"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch in tests
        return False, str(exc)
    return True, f"artifact directory is writable: {artifact_dir}"


def _append(results: list[CheckResult], level: str, summary: str, detail: str) -> None:
    results.append(CheckResult(level=level, summary=summary, detail=detail))


def _validate_runtime_config(config: PreflightConfig) -> list[CheckResult]:
    results: list[CheckResult] = []
    if config.trainer_backend in SUPPORTED_TRAINER_BACKENDS:
        _append(
            results,
            "ok",
            "Trainer backend",
            f"FT_TRAINER_BACKEND={config.trainer_backend} matches the supported MLX training backend.",
        )
    else:
        _append(
            results,
            "fail",
            "Trainer backend",
            (
                f"FT_TRAINER_BACKEND={config.trainer_backend} is not supported by the Mac-native trainer. "
                f"Supported values: {', '.join(sorted(SUPPORTED_TRAINER_BACKENDS))}."
            ),
        )

    if config.default_training_method in SUPPORTED_TRAINING_METHODS:
        _append(
            results,
            "ok",
            "Training method",
            f"FT_DEFAULT_TRAINING_METHOD={config.default_training_method} matches the supported MLX training method.",
        )
    else:
        _append(
            results,
            "fail",
            "Training method",
            (
                f"FT_DEFAULT_TRAINING_METHOD={config.default_training_method} is not supported by the Mac-native trainer. "
                f"Supported values: {', '.join(sorted(SUPPORTED_TRAINING_METHODS))}."
            ),
        )
    return results


def run_preflight(
    config: PreflightConfig | None = None,
    *,
    api_health_checker=check_api_health,
    dependency_inspector=inspect_dependencies,
    device_inspector=inspect_mlx_runtime,
    artifact_dir_checker=check_artifact_dir,
    lmstudio_inspector=inspect_lmstudio,
) -> list[CheckResult]:
    config = config or load_config()
    results: list[CheckResult] = []

    api_ok, api_detail = api_health_checker(config.api_base_url)
    _append(
        results,
        "ok" if api_ok else "fail",
        "API health",
        (
            f"GET {config.api_base_url}/health responded successfully."
            if api_ok
            else f"GET {config.api_base_url}/health failed: {api_detail}"
        ),
    )

    lmstudio = lmstudio_inspector(
        config.lmstudio_base_url,
        chat_model=config.lmstudio_chat_model,
        embed_model=config.lmstudio_embed_model,
    )
    if not lmstudio.reachable:
        _append(
            results,
            "warn",
            "LM Studio runtime",
            (
                f"{lmstudio.detail} Inference and RAG retrieval will fail until "
                "LM Studio is reachable. Open LM Studio → Local Server tab and start the server."
            ),
        )
    else:
        chat_ok = lmstudio.chat_model_loaded or not config.lmstudio_chat_model
        embed_ok = lmstudio.embed_model_loaded or not config.lmstudio_embed_model
        if chat_ok and embed_ok:
            _append(
                results,
                "ok",
                "LM Studio runtime",
                lmstudio.detail,
            )
        else:
            missing = []
            if config.lmstudio_chat_model and not lmstudio.chat_model_loaded:
                missing.append(f"chat={config.lmstudio_chat_model}")
            if config.lmstudio_embed_model and not lmstudio.embed_model_loaded:
                missing.append(f"embed={config.lmstudio_embed_model}")
            _append(
                results,
                "warn",
                "LM Studio runtime",
                (
                    f"LM Studio reachable but configured models are not loaded: {', '.join(missing)}. "
                    f"Loaded: {lmstudio.detail}. Load the model(s) in LM Studio's Local Server tab."
                ),
            )

    dependencies = dependency_inspector()
    missing = [item for item in dependencies if not item.available]
    if missing:
        names = ", ".join(sorted(item.name for item in missing))
        _append(
            results,
            "fail",
            "MLX CLI tools",
            f"Missing MLX training tools: {names}. Install/update with `brew install mlx mlx-lm`.",
        )
    else:
        details = "; ".join(item.detail for item in dependencies)
        _append(
            results,
            "ok",
            "MLX CLI tools",
            f"brew mlx-lm tools are available: {details}",
        )

    device_status = device_inspector()
    if not device_status.mlx_available:
        _append(
            results,
            "fail",
            "MLX Metal runtime",
            f"MLX import failed in the host Python runtime: {device_status.detail}",
        )
    elif not device_status.metal_available:
        _append(
            results,
            "fail",
            "MLX Metal runtime",
            f"MLX imported but Metal is unavailable: {device_status.detail}",
        )
    else:
        _append(
            results,
            "ok",
            "MLX Metal runtime",
            f"MLX Metal is available ({device_status.detail}).",
        )

    env_details = [
        f"MODEL_ARTIFACT_DIR={config.artifact_dir}",
        f"FT_TRAINER_BACKEND={config.trainer_backend}",
        f"FT_DEFAULT_TRAINING_METHOD={config.default_training_method}",
    ]
    _append(
        results,
        "ok",
        "Training environment variables",
        "; ".join(env_details),
    )

    results.extend(_validate_runtime_config(config))

    try:
        parsed_model_map = json.loads(config.trainer_model_map_json)
    except json.JSONDecodeError as exc:
        _append(
            results,
            "fail",
            "Trainer model map",
            f"FT_TRAINER_MODEL_MAP_JSON is not valid JSON: {exc}",
        )
    else:
        if isinstance(parsed_model_map, dict) and parsed_model_map:
            mapped_values = ", ".join(str(value) for value in parsed_model_map.values())
            _append(
                results,
                "ok",
                "Trainer model map",
                f"FT_TRAINER_MODEL_MAP_JSON is configured. Current mapped trainer models: {mapped_values}",
            )
        else:
            _append(
                results,
                "warn",
                "Trainer model map",
                "FT_TRAINER_MODEL_MAP_JSON is empty. Runs can still supply trainer_model_name explicitly in the enqueue payload.",
            )

    artifact_ok, artifact_detail = artifact_dir_checker(config.artifact_dir)
    _append(
        results,
        "ok" if artifact_ok else "fail",
        "Artifact directory",
        artifact_detail,
    )

    _append(
        results,
        "warn",
        "Tiny trainer model access",
        (
            f"The MLX smoke path typically resolves to {EXPECTED_TINY_MODEL}. If that model is not cached, the first run may need network access."
        ),
    )

    return results


def format_results(results: list[CheckResult]) -> str:
    return "\n".join(
        f"[{result.level}] {result.summary}: {result.detail}" for result in results
    )


def exit_code_for_results(results: list[CheckResult]) -> int:
    return 1 if any(result.level == "fail" for result in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ft-smoke-preflight",
        description="Check Mac-native MLX fine-tuning prerequisites.",
    )
    parser.add_argument(
        "--api-base-url",
        default=None,
        help="Override API_BASE_URL for the /health check.",
    )
    args = parser.parse_args(argv)

    if args.api_base_url is not None:
        os.environ["API_BASE_URL"] = args.api_base_url

    results = run_preflight()
    print(format_results(results), flush=True)
    return exit_code_for_results(results)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
