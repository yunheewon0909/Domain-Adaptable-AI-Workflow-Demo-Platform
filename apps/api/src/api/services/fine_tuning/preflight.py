from __future__ import annotations

from dataclasses import dataclass
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request


EXPECTED_DEPENDENCIES = ("torch", "transformers", "peft", "datasets", "accelerate")
EXPECTED_TINY_MODEL = "hf-internal/testing-tiny-random-gpt2"


@dataclass(frozen=True)
class CheckResult:
    level: str
    summary: str
    detail: str


@dataclass(frozen=True)
class PackageStatus:
    name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class DeviceStatus:
    torch_available: bool
    cuda_available: bool
    mps_available: bool
    detail: str = ""


@dataclass(frozen=True)
class ComposeStatus:
    available: bool
    running_services: tuple[str, ...]
    detail: str


@dataclass(frozen=True)
class PreflightConfig:
    api_base_url: str
    worker_runtime: str
    current_runtime: str
    training_device: str
    training_allow_cpu: bool
    artifact_dir: Path
    trainer_backend: str
    default_training_method: str
    trainer_model_map_json: str
    project_root: Path


def _find_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "compose.yml").exists() and (parent / "apps").exists():
            return parent
    return Path.cwd()


def _detect_current_runtime() -> str:
    return "docker" if Path("/.dockerenv").exists() else "host"


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_worker_runtime(raw_value: str | None, *, current_runtime: str) -> str:
    normalized = (raw_value or "auto").strip().lower()
    if normalized in {"", "auto", "current"}:
        return current_runtime
    if normalized in {"host", "docker"}:
        return normalized
    return current_runtime


def load_config() -> PreflightConfig:
    project_root = _find_project_root()
    current_runtime = _detect_current_runtime()
    artifact_dir_raw = os.getenv("MODEL_ARTIFACT_DIR", "data/model_artifacts")
    artifact_dir = Path(artifact_dir_raw)
    if not artifact_dir.is_absolute():
        artifact_dir = project_root / artifact_dir
    return PreflightConfig(
        api_base_url=os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        worker_runtime=_normalize_worker_runtime(
            os.getenv("FT_SMOKE_WORKER_RUNTIME"), current_runtime=current_runtime
        ),
        current_runtime=current_runtime,
        training_device=(
            os.getenv("TRAINING_DEVICE", "auto").strip().lower() or "auto"
        ),
        training_allow_cpu=_parse_bool(os.getenv("TRAINING_ALLOW_CPU"), default=False),
        artifact_dir=artifact_dir,
        trainer_backend=os.getenv("FT_TRAINER_BACKEND", "local_peft").strip()
        or "local_peft",
        default_training_method=os.getenv(
            "FT_DEFAULT_TRAINING_METHOD", "sft_lora"
        ).strip()
        or "sft_lora",
        trainer_model_map_json=os.getenv("FT_TRAINER_MODEL_MAP_JSON", "{}"),
        project_root=project_root,
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


def inspect_dependencies() -> list[PackageStatus]:
    packages: list[PackageStatus] = []
    for name in EXPECTED_DEPENDENCIES:
        try:
            importlib.import_module(name)
        except (
            Exception
        ) as exc:  # pragma: no cover - exercised via monkeypatch in tests
            packages.append(PackageStatus(name=name, available=False, detail=str(exc)))
        else:
            packages.append(
                PackageStatus(name=name, available=True, detail="import ok")
            )
    return packages


def inspect_torch_devices() -> DeviceStatus:
    try:
        torch = importlib.import_module("torch")
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch in tests
        return DeviceStatus(
            torch_available=False,
            cuda_available=False,
            mps_available=False,
            detail=str(exc),
        )

    cuda_available = bool(torch.cuda.is_available())
    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    mps_available = bool(mps_backend and mps_backend.is_available())
    return DeviceStatus(
        torch_available=True,
        cuda_available=cuda_available,
        mps_available=mps_available,
        detail="torch import ok",
    )


def inspect_compose_services(project_root: Path) -> ComposeStatus:
    compose_file = project_root / "compose.yml"
    if not compose_file.exists():
        return ComposeStatus(
            available=False,
            running_services=(),
            detail="compose.yml not found; skipping docker compose status check.",
        )
    try:
        completed = subprocess.run(
            ["docker", "compose", "ps", "--services", "--status", "running"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return ComposeStatus(
            available=False,
            running_services=(),
            detail="docker compose is not available in this shell.",
        )

    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "docker compose ps failed"
        )
        return ComposeStatus(available=False, running_services=(), detail=detail)

    services = tuple(
        line.strip() for line in completed.stdout.splitlines() if line.strip()
    )
    detail = (
        f"running services: {', '.join(services)}"
        if services
        else "no running compose services were reported"
    )
    return ComposeStatus(available=True, running_services=services, detail=detail)


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


def run_preflight(
    config: PreflightConfig | None = None,
    *,
    api_health_checker=check_api_health,
    dependency_inspector=inspect_dependencies,
    device_inspector=inspect_torch_devices,
    compose_inspector=inspect_compose_services,
    artifact_dir_checker=check_artifact_dir,
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

    _append(
        results,
        "ok",
        "Worker runtime target",
        (
            f"Current Python runtime: {config.current_runtime}. Smoke-training worker target: {config.worker_runtime}. "
            "The training device is validated where the worker subprocess runs, not where the HTTP API is hosted."
        ),
    )
    if config.worker_runtime != config.current_runtime:
        _append(
            results,
            "warn",
            "Runtime mismatch",
            (
                f"You are checking from a {config.current_runtime} shell while targeting a {config.worker_runtime} worker. "
                "Dependency and device checks below describe the current Python runtime, so use them as guidance unless you run the preflight from the actual worker environment."
            ),
        )

    compose_status = compose_inspector(config.project_root)
    if compose_status.available:
        if "worker" in compose_status.running_services:
            level = "ok"
            detail = f"docker compose reports the worker service as running ({compose_status.detail})."
        else:
            level = "warn"
            detail = (
                f"docker compose status is available but the worker service is not running ({compose_status.detail}). "
                "This is acceptable for a host-worker smoke path, but queue-backed training still needs some worker runtime to consume jobs."
            )
        _append(results, level, "Worker/container status", detail)
    else:
        _append(
            results,
            "warn",
            "Worker/container status",
            (
                f"Could not confirm docker compose worker status: {compose_status.detail} "
                "This is non-fatal because host-worker smoke validation is allowed."
            ),
        )

    dependencies = dependency_inspector()
    missing = [item for item in dependencies if not item.available]
    if missing:
        names = ", ".join(sorted(item.name for item in missing))
        _append(
            results,
            "fail",
            "Python dependencies",
            f"Missing training dependencies: {names}. The local smoke path needs torch, transformers, peft, datasets, and accelerate in the runtime that will execute training.",
        )
    else:
        _append(
            results,
            "ok",
            "Python dependencies",
            "torch, transformers, peft, datasets, and accelerate imported successfully in the current Python runtime.",
        )

    device_status = device_inspector()
    if not device_status.torch_available:
        _append(
            results,
            "fail",
            "PyTorch device detection",
            f"torch import failed, so device checks could not run: {device_status.detail}",
        )
    else:
        _append(
            results,
            "ok",
            "PyTorch device detection",
            (
                f"cuda_available={device_status.cuda_available}, mps_available={device_status.mps_available}, "
                f"training_device={config.training_device}, training_allow_cpu={config.training_allow_cpu}."
            ),
        )

        if config.training_device == "mps":
            if config.worker_runtime == "docker":
                _append(
                    results,
                    "fail",
                    "MPS worker topology",
                    "TRAINING_DEVICE=mps is a host-worker validation path. Standard Docker Linux workers should not be treated as MPS-capable.",
                )
            elif not device_status.mps_available:
                _append(
                    results,
                    "fail",
                    "MPS availability",
                    "TRAINING_DEVICE=mps was requested but torch.backends.mps.is_available() is false in the current host runtime.",
                )
            else:
                _append(
                    results,
                    "ok",
                    "MPS availability",
                    "MPS is available in the current host runtime, so this machine can validate the Apple Silicon host-worker smoke path.",
                )
        elif config.training_device == "cuda":
            _append(
                results,
                "ok" if device_status.cuda_available else "fail",
                "CUDA availability",
                (
                    "CUDA is available in the current runtime."
                    if device_status.cuda_available
                    else "TRAINING_DEVICE=cuda was requested but torch.cuda.is_available() is false."
                ),
            )
        elif config.training_device == "cpu":
            _append(
                results,
                "ok" if config.training_allow_cpu else "fail",
                "CPU fallback policy",
                (
                    "CPU smoke runs are explicitly enabled for this runtime."
                    if config.training_allow_cpu
                    else "TRAINING_DEVICE=cpu was requested while TRAINING_ALLOW_CPU is false. CPU fallback is intentionally opt-in for tiny smoke runs only."
                ),
            )
        else:
            if device_status.cuda_available:
                _append(
                    results,
                    "ok",
                    "Auto device resolution",
                    "Auto mode can resolve to CUDA in the current runtime.",
                )
            elif config.worker_runtime == "host" and device_status.mps_available:
                _append(
                    results,
                    "ok",
                    "Auto device resolution",
                    "Auto mode can resolve to MPS in the current host runtime.",
                )
            elif config.training_allow_cpu:
                _append(
                    results,
                    "warn",
                    "Auto device resolution",
                    "No accelerator was detected in the current runtime, but TRAINING_ALLOW_CPU=true permits a tiny CPU smoke run.",
                )
            else:
                _append(
                    results,
                    "fail",
                    "Auto device resolution",
                    "No accelerator was detected and TRAINING_ALLOW_CPU=false. The smoke job will fail unless you switch to a host-MPS/CUDA path or deliberately enable tiny CPU fallback.",
                )

    env_details = [
        f"TRAINING_DEVICE={config.training_device}",
        f"TRAINING_ALLOW_CPU={str(config.training_allow_cpu).lower()}",
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
                "FT_TRAINER_MODEL_MAP_JSON is empty. Smoke runs will need trainer_model_name supplied explicitly in the enqueue payload.",
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
            f"The smoke path typically resolves to {EXPECTED_TINY_MODEL}. If that model or tokenizer is not already cached, the first run may need network access to download it."
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
        description="Check local fine-tuning smoke-training runtime prerequisites.",
    )
    parser.add_argument(
        "--api-base-url",
        default=None,
        help="Override API_BASE_URL for the /health check.",
    )
    parser.add_argument(
        "--worker-runtime",
        choices=("auto", "current", "host", "docker"),
        default=None,
        help="Describe where the smoke-training worker will run.",
    )
    args = parser.parse_args(argv)

    if args.api_base_url is not None:
        os.environ["API_BASE_URL"] = args.api_base_url
    if args.worker_runtime is not None:
        os.environ["FT_SMOKE_WORKER_RUNTIME"] = args.worker_runtime

    results = run_preflight()
    print(format_results(results), flush=True)
    return exit_code_for_results(results)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
