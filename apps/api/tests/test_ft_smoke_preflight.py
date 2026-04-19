from __future__ import annotations

from pathlib import Path

from api.services.fine_tuning.preflight import (
    CheckResult,
    ComposeStatus,
    DeviceStatus,
    PackageStatus,
    PreflightConfig,
    exit_code_for_results,
    format_results,
    run_preflight,
)


def _config(
    tmp_path: Path,
    *,
    api_base_url: str = "http://127.0.0.1:8000",
    worker_runtime: str = "host",
    current_runtime: str = "host",
    training_device: str = "auto",
    training_allow_cpu: bool = False,
    trainer_model_map_json: str = '{"qwen2.5:7b-instruct-q4_K_M":"hf-internal/testing-tiny-random-gpt2"}',
    trainer_backend: str = "local_peft",
    default_training_method: str = "sft_lora",
) -> PreflightConfig:
    return PreflightConfig(
        api_base_url=api_base_url,
        worker_runtime=worker_runtime,
        current_runtime=current_runtime,
        training_device=training_device,
        training_allow_cpu=training_allow_cpu,
        artifact_dir=tmp_path / "artifacts",
        trainer_backend=trainer_backend,
        default_training_method=default_training_method,
        trainer_model_map_json=trainer_model_map_json,
        project_root=tmp_path,
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


def _device_status(
    *,
    torch_available: bool = True,
    cuda_available: bool = False,
    mps_available: bool = False,
    detail: str = "torch ok",
) -> DeviceStatus:
    return DeviceStatus(
        torch_available=torch_available,
        cuda_available=cuda_available,
        mps_available=mps_available,
        detail=detail,
    )


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


def _run_preflight(
    config: PreflightConfig,
    *,
    api_ok: bool = True,
    api_detail: str = '{"status":"ok"}',
    missing_dependencies: tuple[str, ...] = (),
    device_status: DeviceStatus | None = None,
    compose_status: ComposeStatus | None = None,
    artifact_ok: bool = True,
    artifact_detail: str | None = None,
) -> list[CheckResult]:
    device_status = device_status or _device_status()
    compose_status = compose_status or _compose_status()
    return run_preflight(
        config,
        api_health_checker=lambda _: (api_ok, api_detail),
        dependency_inspector=lambda: _package_statuses(missing=missing_dependencies),
        device_inspector=lambda: device_status,
        compose_inspector=lambda _: compose_status,
        artifact_dir_checker=lambda _: (
            artifact_ok,
            artifact_detail
            or (
                f"artifact directory is writable: {config.artifact_dir}"
                if artifact_ok
                else "artifact directory is not writable"
            ),
        ),
    )


def _result(results: list[CheckResult], summary: str) -> CheckResult:
    return next(result for result in results if result.summary == summary)


def test_preflight_fails_when_api_health_check_fails(tmp_path: Path) -> None:
    config = _config(tmp_path)

    results = _run_preflight(
        config,
        api_ok=False,
        api_detail="connection refused",
    )

    api_result = _result(results, "API health")
    assert api_result.level == "fail"
    assert "connection refused" in api_result.detail
    assert exit_code_for_results(results) == 1


def test_preflight_fails_when_required_dependencies_are_missing(tmp_path: Path) -> None:
    config = _config(tmp_path, training_allow_cpu=True)

    results = _run_preflight(config, missing_dependencies=("torch",))

    dependency_result = _result(results, "Python dependencies")
    assert dependency_result.level == "fail"
    assert "torch" in dependency_result.detail


def test_preflight_fails_for_docker_mps_runtime(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        worker_runtime="docker",
        current_runtime="host",
        training_device="mps",
    )

    results = _run_preflight(
        config,
        device_status=_device_status(mps_available=True),
        compose_status=_compose_status(running_services=("postgres", "api", "worker")),
    )

    topology_result = _result(results, "MPS worker topology")
    assert topology_result.level == "fail"
    assert (
        "Docker Linux workers should not be treated as MPS-capable"
        in topology_result.detail
    )
    assert _result(results, "Runtime mismatch").level == "warn"


def test_preflight_fails_when_host_mps_is_unavailable(tmp_path: Path) -> None:
    config = _config(tmp_path, training_device="mps")

    results = _run_preflight(
        config,
        device_status=_device_status(mps_available=False),
    )

    mps_result = _result(results, "MPS availability")
    assert mps_result.level == "fail"
    assert "torch.backends.mps.is_available() is false" in mps_result.detail


def test_preflight_fails_when_cpu_runtime_is_not_explicitly_enabled(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, training_device="cpu", training_allow_cpu=False)

    results = _run_preflight(config)

    cpu_result = _result(results, "CPU fallback policy")
    assert cpu_result.level == "fail"
    assert "TRAINING_DEVICE=cpu was requested" in cpu_result.detail


def test_preflight_fails_auto_mode_without_accelerator_or_cpu_opt_in(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, training_device="auto", training_allow_cpu=False)

    results = _run_preflight(
        config,
        device_status=_device_status(cuda_available=False, mps_available=False),
    )

    auto_result = _result(results, "Auto device resolution")
    assert auto_result.level == "fail"
    assert "TRAINING_ALLOW_CPU=false" in auto_result.detail


def test_preflight_fails_when_artifact_directory_is_not_writable(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    results = _run_preflight(
        config,
        artifact_ok=False,
        artifact_detail="permission denied",
    )

    artifact_result = _result(results, "Artifact directory")
    assert artifact_result.level == "fail"
    assert artifact_result.detail == "permission denied"


def test_preflight_warns_when_trainer_model_map_is_empty(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        trainer_model_map_json="{}",
        training_allow_cpu=True,
    )

    results = _run_preflight(config)

    model_map_result = _result(results, "Trainer model map")
    assert model_map_result.level == "warn"
    assert "supplied explicitly in the enqueue payload" in model_map_result.detail


def test_preflight_accepts_host_mps_runtime(tmp_path: Path) -> None:
    config = _config(tmp_path, training_device="mps")

    results = _run_preflight(
        config,
        device_status=_device_status(mps_available=True),
    )

    assert exit_code_for_results(results) == 0
    assert _result(results, "MPS availability").level == "ok"
    assert _result(results, "Artifact directory").level == "ok"
    assert not any(result.level == "fail" for result in results)


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


def test_docker_demo_defaults_are_documented_in_compose_and_env_example() -> None:
    project_root = Path(__file__).resolve().parents[3]
    compose_text = (project_root / "compose.yml").read_text(encoding="utf-8")
    env_example_text = (project_root / ".env.example").read_text(encoding="utf-8")

    assert "TRAINING_DEVICE: cpu" in compose_text
    assert 'TRAINING_ALLOW_CPU: "true"' in compose_text
    assert 'FT_MAX_SEQ_LENGTH: "256"' in compose_text
    assert "MODEL_ARTIFACT_DIR: /workspace/data/model_artifacts" in compose_text
    assert 'OLLAMA_PUBLISH_ENABLED: "false"' in compose_text
    assert "Docker CPU smoke profile" in env_example_text
    assert "Host Apple Silicon MPS profile" in env_example_text


def test_preflight_fails_for_unsupported_backend(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        training_allow_cpu=True,
        trainer_backend="mystery_backend",
    )

    results = _run_preflight(config)

    backend_result = _result(results, "Trainer backend")
    assert backend_result.level == "fail"
    assert "local_peft" in backend_result.detail


def test_preflight_fails_for_unsupported_training_method(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        training_allow_cpu=True,
        default_training_method="full_finetune",
    )

    results = _run_preflight(config)

    method_result = _result(results, "Training method")
    assert method_result.level == "fail"
    assert "sft_lora" in method_result.detail
