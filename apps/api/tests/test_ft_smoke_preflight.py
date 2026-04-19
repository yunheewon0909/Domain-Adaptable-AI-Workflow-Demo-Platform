from __future__ import annotations

import json
from pathlib import Path

from api.services.fine_tuning.preflight import (
    CheckResult,
    ComposeStatus,
    DeviceStatus,
    PackageStatus,
    exit_code_for_results,
    format_results,
    load_config,
    run_preflight,
)


def _package_statuses(*, missing: tuple[str, ...] = ()) -> list[PackageStatus]:
    return [
        PackageStatus(
            name=name,
            available=name not in missing,
            detail="missing" if name in missing else "import ok",
        )
        for name in ("torch", "transformers", "peft", "datasets", "accelerate")
    ]


def _compose_status(*, running_services: tuple[str, ...] = ()) -> ComposeStatus:
    return ComposeStatus(
        available=True,
        running_services=running_services,
        detail=(
            f"running services: {', '.join(running_services)}"
            if running_services
            else "no running compose services were reported"
        ),
    )


def test_preflight_accepts_host_mps_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("FT_SMOKE_WORKER_RUNTIME", "host")
    monkeypatch.setenv("TRAINING_DEVICE", "mps")
    monkeypatch.setenv("TRAINING_ALLOW_CPU", "false")
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv(
        "FT_TRAINER_MODEL_MAP_JSON",
        json.dumps(
            {"qwen2.5:7b-instruct-q4_K_M": "hf-internal/testing-tiny-random-gpt2"}
        ),
    )
    monkeypatch.setattr(
        "api.services.fine_tuning.preflight._detect_current_runtime", lambda: "host"
    )

    config = load_config()
    results = run_preflight(
        config,
        api_health_checker=lambda _: (True, '{"status":"ok"}'),
        dependency_inspector=lambda: _package_statuses(),
        device_inspector=lambda: DeviceStatus(
            torch_available=True,
            cuda_available=False,
            mps_available=True,
            detail="torch ok",
        ),
        compose_inspector=lambda _: _compose_status(),
    )

    assert exit_code_for_results(results) == 0
    formatted = format_results(results)
    assert "[ok] MPS availability" in formatted
    assert "host-worker smoke path" in formatted
    assert "[ok] Artifact directory" in formatted


def test_preflight_fails_for_docker_mps_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FT_SMOKE_WORKER_RUNTIME", "docker")
    monkeypatch.setenv("TRAINING_DEVICE", "mps")
    monkeypatch.setenv("TRAINING_ALLOW_CPU", "false")
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FT_TRAINER_MODEL_MAP_JSON", "{}")
    monkeypatch.setattr(
        "api.services.fine_tuning.preflight._detect_current_runtime", lambda: "host"
    )

    config = load_config()
    results = run_preflight(
        config,
        api_health_checker=lambda _: (True, '{"status":"ok"}'),
        dependency_inspector=lambda: _package_statuses(),
        device_inspector=lambda: DeviceStatus(
            torch_available=True,
            cuda_available=False,
            mps_available=True,
            detail="torch ok",
        ),
        compose_inspector=lambda _: _compose_status(
            running_services=("postgres", "api", "worker")
        ),
    )

    assert exit_code_for_results(results) == 1
    assert any(
        result.level == "fail" and result.summary == "MPS worker topology"
        for result in results
    )
    assert any(
        result.level == "warn" and result.summary == "Runtime mismatch"
        for result in results
    )


def test_preflight_fails_when_required_dependencies_are_missing(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_SMOKE_WORKER_RUNTIME", "host")
    monkeypatch.setenv("TRAINING_DEVICE", "auto")
    monkeypatch.setenv("TRAINING_ALLOW_CPU", "true")
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FT_TRAINER_MODEL_MAP_JSON", "{}")
    monkeypatch.setattr(
        "api.services.fine_tuning.preflight._detect_current_runtime", lambda: "host"
    )

    config = load_config()
    results = run_preflight(
        config,
        api_health_checker=lambda _: (True, '{"status":"ok"}'),
        dependency_inspector=lambda: _package_statuses(
            missing=("peft", "transformers")
        ),
        device_inspector=lambda: DeviceStatus(
            torch_available=True,
            cuda_available=False,
            mps_available=False,
            detail="torch ok",
        ),
        compose_inspector=lambda _: _compose_status(),
    )

    assert exit_code_for_results(results) == 1
    failure = next(
        result for result in results if result.summary == "Python dependencies"
    )
    assert failure.level == "fail"
    assert "peft, transformers" in failure.detail


def test_preflight_fails_auto_mode_without_accelerator_or_cpu_opt_in(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_SMOKE_WORKER_RUNTIME", "host")
    monkeypatch.setenv("TRAINING_DEVICE", "auto")
    monkeypatch.setenv("TRAINING_ALLOW_CPU", "false")
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FT_TRAINER_MODEL_MAP_JSON", "{}")
    monkeypatch.setattr(
        "api.services.fine_tuning.preflight._detect_current_runtime", lambda: "host"
    )

    config = load_config()
    results = run_preflight(
        config,
        api_health_checker=lambda _: (True, '{"status":"ok"}'),
        dependency_inspector=lambda: _package_statuses(),
        device_inspector=lambda: DeviceStatus(
            torch_available=True,
            cuda_available=False,
            mps_available=False,
            detail="torch ok",
        ),
        compose_inspector=lambda _: _compose_status(),
    )

    assert exit_code_for_results(results) == 1
    auto_result = next(
        result for result in results if result.summary == "Auto device resolution"
    )
    assert auto_result.level == "fail"
    assert "TRAINING_ALLOW_CPU=false" in auto_result.detail


def test_preflight_output_uses_tagged_lines() -> None:
    formatted = format_results(
        [
            CheckResult(level="ok", summary="API health", detail="ready"),
            CheckResult(level="warn", summary="Worker/container status", detail="host"),
            CheckResult(
                level="fail", summary="Python dependencies", detail="missing torch"
            ),
        ]
    )

    assert "[ok] API health: ready" in formatted
    assert "[warn] Worker/container status: host" in formatted
    assert "[fail] Python dependencies: missing torch" in formatted


def test_preflight_fails_for_unsupported_backend(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FT_SMOKE_WORKER_RUNTIME", "host")
    monkeypatch.setenv("TRAINING_DEVICE", "auto")
    monkeypatch.setenv("TRAINING_ALLOW_CPU", "true")
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FT_TRAINER_BACKEND", "mystery_backend")
    monkeypatch.setenv("FT_DEFAULT_TRAINING_METHOD", "sft_lora")
    monkeypatch.setenv("FT_TRAINER_MODEL_MAP_JSON", "{}")
    monkeypatch.setattr(
        "api.services.fine_tuning.preflight._detect_current_runtime", lambda: "host"
    )

    config = load_config()
    results = run_preflight(
        config,
        api_health_checker=lambda _: (True, '{"status":"ok"}'),
        dependency_inspector=lambda: _package_statuses(),
        device_inspector=lambda: DeviceStatus(
            torch_available=True,
            cuda_available=False,
            mps_available=False,
            detail="torch ok",
        ),
        compose_inspector=lambda _: _compose_status(),
    )

    backend_result = next(
        result for result in results if result.summary == "Trainer backend"
    )
    assert backend_result.level == "fail"
    assert "local_peft" in backend_result.detail


def test_preflight_fails_for_unsupported_training_method(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FT_SMOKE_WORKER_RUNTIME", "host")
    monkeypatch.setenv("TRAINING_DEVICE", "auto")
    monkeypatch.setenv("TRAINING_ALLOW_CPU", "true")
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FT_TRAINER_BACKEND", "local_peft")
    monkeypatch.setenv("FT_DEFAULT_TRAINING_METHOD", "full_finetune")
    monkeypatch.setenv("FT_TRAINER_MODEL_MAP_JSON", "{}")
    monkeypatch.setattr(
        "api.services.fine_tuning.preflight._detect_current_runtime", lambda: "host"
    )

    config = load_config()
    results = run_preflight(
        config,
        api_health_checker=lambda _: (True, '{"status":"ok"}'),
        dependency_inspector=lambda: _package_statuses(),
        device_inspector=lambda: DeviceStatus(
            torch_available=True,
            cuda_available=False,
            mps_available=False,
            detail="torch ok",
        ),
        compose_inspector=lambda _: _compose_status(),
    )

    method_result = next(
        result for result in results if result.summary == "Training method"
    )
    assert method_result.level == "fail"
    assert "sft_lora" in method_result.detail
