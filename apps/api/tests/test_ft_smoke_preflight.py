from __future__ import annotations

from pathlib import Path

from api.services.fine_tuning.preflight import (
    CheckResult,
    DeviceStatus,
    LMStudioStatus,
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
    trainer_model_map_json: str = '{"qwen3.5:4b":"mlx-community/Qwen2.5-0.5B-Instruct-4bit"}',
    trainer_backend: str = "mlx_qlora",
    default_training_method: str = "sft_qlora",
    lmstudio_chat_model: str = "lmstudio-chat",
    lmstudio_embed_model: str = "lmstudio-embed",
) -> PreflightConfig:
    return PreflightConfig(
        api_base_url=api_base_url,
        artifact_dir=tmp_path,
        trainer_backend=trainer_backend,
        default_training_method=default_training_method,
        trainer_model_map_json=trainer_model_map_json,
        project_root=tmp_path,
        lmstudio_base_url="http://127.0.0.1:1234/v1",
        lmstudio_chat_model=lmstudio_chat_model,
        lmstudio_embed_model=lmstudio_embed_model,
    )


def _cli_statuses(*, missing: tuple[str, ...] = ()) -> list[PackageStatus]:
    return [
        PackageStatus(
            name=name,
            available=name not in missing,
            detail="missing" if name in missing else f"/opt/homebrew/bin/{name} --help ok",
        )
        for name in ("mlx_lm.lora", "mlx_lm.fuse")
    ]


def _device_status(
    *,
    mlx_available: bool = True,
    metal_available: bool = True,
    detail: str = "python3.14: metal=true",
) -> DeviceStatus:
    return DeviceStatus(
        mlx_available=mlx_available,
        metal_available=metal_available,
        detail=detail,
    )


def _result(results: list[CheckResult], summary: str) -> CheckResult:
    for item in results:
        if item.summary == summary:
            return item
    raise AssertionError(f"No CheckResult with summary={summary!r} in {results!r}")


def _lmstudio_status(
    *,
    reachable: bool = True,
    loaded: tuple[str, ...] = ("lmstudio-chat", "lmstudio-embed"),
    chat_loaded: bool = True,
    embed_loaded: bool = True,
    detail: str = "2 model(s) loaded: lmstudio-chat, lmstudio-embed",
) -> LMStudioStatus:
    return LMStudioStatus(
        reachable=reachable,
        loaded_models=loaded,
        chat_model_loaded=chat_loaded,
        embed_model_loaded=embed_loaded,
        detail=detail,
    )


def _run_preflight(
    config: PreflightConfig,
    *,
    api_ok: bool = True,
    api_detail: str = '{"status":"ok"}',
    missing_tools: tuple[str, ...] = (),
    device_status: DeviceStatus | None = None,
    artifact_ok: bool = True,
    artifact_detail: str | None = None,
    lmstudio_status: LMStudioStatus | None = None,
) -> list[CheckResult]:
    device_status = device_status or _device_status()
    lmstudio_status = lmstudio_status or _lmstudio_status()
    return run_preflight(
        config,
        api_health_checker=lambda _: (api_ok, api_detail),
        dependency_inspector=lambda: _cli_statuses(missing=missing_tools),
        device_inspector=lambda: device_status,
        artifact_dir_checker=lambda _: (
            artifact_ok,
            artifact_detail
            or (
                f"artifact directory is writable: {config.artifact_dir}"
                if artifact_ok
                else "artifact directory is not writable"
            ),
        ),
        lmstudio_inspector=lambda *_args, **_kwargs: lmstudio_status,
    )


def test_preflight_fails_when_api_health_check_fails(tmp_path: Path) -> None:
    config = _config(tmp_path)

    results = _run_preflight(
        config,
        api_ok=False,
        api_detail="Connection refused",
    )

    health_result = _result(results, "API health")
    assert health_result.level == "fail"
    assert "Connection refused" in health_result.detail
    assert exit_code_for_results(results) == 1


def test_preflight_fails_when_mlx_lm_cli_is_missing(tmp_path: Path) -> None:
    config = _config(tmp_path)

    results = _run_preflight(config, missing_tools=("mlx_lm.lora",))

    cli_result = _result(results, "MLX CLI tools")
    assert cli_result.level == "fail"
    assert "mlx_lm.lora" in cli_result.detail
    assert "brew install mlx mlx-lm" in cli_result.detail


def test_preflight_fails_when_mlx_import_fails(tmp_path: Path) -> None:
    config = _config(tmp_path)

    results = _run_preflight(
        config,
        device_status=_device_status(
            mlx_available=False,
            metal_available=False,
            detail="No module named mlx",
        ),
    )

    mlx_result = _result(results, "MLX Metal runtime")
    assert mlx_result.level == "fail"
    assert "No module named mlx" in mlx_result.detail


def test_preflight_fails_when_metal_is_unavailable(tmp_path: Path) -> None:
    config = _config(tmp_path)

    results = _run_preflight(
        config,
        device_status=_device_status(metal_available=False, detail="metal=false"),
    )

    metal_result = _result(results, "MLX Metal runtime")
    assert metal_result.level == "fail"
    assert "Metal is unavailable" in metal_result.detail


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
    assert "permission denied" in artifact_result.detail


def test_preflight_warns_when_trainer_model_map_is_empty(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        trainer_model_map_json="{}",
    )

    results = _run_preflight(config)

    model_map_result = _result(results, "Trainer model map")
    assert model_map_result.level == "warn"
    assert "trainer_model_name explicitly" in model_map_result.detail


def test_preflight_accepts_mac_mlx_runtime(tmp_path: Path) -> None:
    config = _config(tmp_path)

    results = _run_preflight(config)

    assert exit_code_for_results(results) == 0
    assert _result(results, "MLX CLI tools").level == "ok"
    assert _result(results, "MLX Metal runtime").level == "ok"
    assert _result(results, "Artifact directory").level == "ok"
    assert not any(result.level == "fail" for result in results)


def test_preflight_output_uses_tagged_lines() -> None:
    formatted = format_results(
        [
            CheckResult(level="ok", summary="API health", detail="ready"),
            CheckResult(level="warn", summary="Trainer model map", detail="empty"),
            CheckResult(
                level="fail", summary="MLX CLI tools", detail="missing mlx_lm.lora"
            ),
        ]
    )

    assert "[ok] API health: ready" in formatted
    assert "[warn] Trainer model map: empty" in formatted
    assert "[fail] MLX CLI tools: missing mlx_lm.lora" in formatted


def test_preflight_fails_for_unsupported_backend(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        trainer_backend="mystery_backend",
    )

    results = _run_preflight(config)

    backend_result = _result(results, "Trainer backend")
    assert backend_result.level == "fail"
    assert "mlx_qlora" in backend_result.detail


def test_preflight_fails_for_unsupported_training_method(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        default_training_method="full_finetune",
    )

    results = _run_preflight(config)

    method_result = _result(results, "Training method")
    assert method_result.level == "fail"
    assert "sft_qlora" in method_result.detail
