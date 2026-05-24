from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from api.services.model_registry.lmstudio_register import (
    loaded_lmstudio_models as _real_loaded_lmstudio_models,
    probe_lmstudio_for_model,
    register_fused_model,
)


def test_register_fused_model_symlinks_files_into_namespaced_target(tmp_path: Path) -> None:
    fused = tmp_path / "fused"
    fused.mkdir()
    (fused / "config.json").write_text("{}", encoding="utf-8")
    (fused / "model.safetensors").write_bytes(b"weights")
    (fused / "tokenizer.json").write_text("{}", encoding="utf-8")

    lmstudio = tmp_path / "lmstudio_models"
    lmstudio.mkdir()

    result = register_fused_model(
        fused_model_dir=fused,
        lmstudio_models_dir=lmstudio,
        namespace="demo",
        model_name="qwen2.5-tuned",
    )

    target = result.target_dir
    assert target is not None
    assert target == lmstudio / "demo" / "qwen2.5-tuned"
    assert target.is_dir()
    assert (target / "config.json").is_symlink()
    assert (target / "model.safetensors").is_symlink()
    assert result.copied_file_count == 3
    assert result.used_symlinks is True


def test_register_fused_model_returns_none_when_lmstudio_dir_missing(
    tmp_path: Path,
) -> None:
    fused = tmp_path / "fused"
    fused.mkdir()
    (fused / "config.json").write_text("{}", encoding="utf-8")

    result = register_fused_model(
        fused_model_dir=fused,
        lmstudio_models_dir=tmp_path / "nope",
        namespace="demo",
        model_name="x",
    )

    assert result.target_dir is None
    assert "does not exist" in result.detail


def test_register_fused_model_returns_none_when_fused_empty(tmp_path: Path) -> None:
    fused = tmp_path / "empty"
    fused.mkdir()
    lmstudio = tmp_path / "lmstudio_models"
    lmstudio.mkdir()

    result = register_fused_model(
        fused_model_dir=fused,
        lmstudio_models_dir=lmstudio,
        namespace="demo",
        model_name="x",
    )

    assert result.target_dir is None
    assert "missing or empty" in result.detail


def test_register_fused_model_overwrites_existing_symlink(tmp_path: Path) -> None:
    fused = tmp_path / "fused"
    fused.mkdir()
    (fused / "config.json").write_text("{}", encoding="utf-8")

    lmstudio = tmp_path / "lmstudio_models"
    target_dir = lmstudio / "demo" / "x"
    target_dir.mkdir(parents=True)
    (target_dir / "config.json").write_text("stale", encoding="utf-8")

    result = register_fused_model(
        fused_model_dir=fused,
        lmstudio_models_dir=lmstudio,
        namespace="demo",
        model_name="x",
    )

    assert result.target_dir == target_dir
    assert (target_dir / "config.json").is_symlink()
    assert (target_dir / "config.json").read_text(encoding="utf-8") == "{}"


def test_probe_lmstudio_returns_true_when_model_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The autouse conftest fixture stubs loaded_lmstudio_models. Restore the
    # real implementation so this test can exercise the urllib path directly.
    from api.services.model_registry import lmstudio_register as _module

    monkeypatch.setattr(_module, "loaded_lmstudio_models", _module.__dict__["loaded_lmstudio_models"].__wrapped__ if hasattr(_module.loaded_lmstudio_models, "__wrapped__") else _real_loaded_lmstudio_models)
    _module.invalidate_loaded_cache()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {"data": [{"id": "demo/x"}, {"id": "demo/y"}]}
            ).encode("utf-8")

    with patch(
        "api.services.model_registry.lmstudio_register.urllib.request.urlopen",
        return_value=_Resp(),
    ):
        assert probe_lmstudio_for_model(
            base_url="http://127.0.0.1:1234/v1", model_id="demo/x"
        ) is True


def test_probe_lmstudio_returns_false_when_model_missing() -> None:
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"data": [{"id": "other/y"}]}).encode("utf-8")

    with patch(
        "api.services.model_registry.lmstudio_register.urllib.request.urlopen",
        return_value=_Resp(),
    ):
        assert probe_lmstudio_for_model(
            base_url="http://127.0.0.1:1234/v1", model_id="demo/x"
        ) is False


def test_probe_lmstudio_returns_false_when_unreachable() -> None:
    import urllib.error

    with patch(
        "api.services.model_registry.lmstudio_register.urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        assert probe_lmstudio_for_model(
            base_url="http://127.0.0.1:1234/v1", model_id="demo/x"
        ) is False


def test_loaded_lmstudio_models_caches_within_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /models probe is cached per base_url for 30s to keep list_models
    cheap on the polling path. Two back-to-back calls hit urllib once.
    """
    from api.services.model_registry import lmstudio_register as _module

    monkeypatch.setattr(
        _module, "loaded_lmstudio_models", _real_loaded_lmstudio_models
    )
    _module.invalidate_loaded_cache()

    call_count = {"n": 0}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            call_count["n"] += 1
            return json.dumps({"data": [{"id": "demo/x"}]}).encode("utf-8")

    with patch(
        "api.services.model_registry.lmstudio_register.urllib.request.urlopen",
        return_value=_Resp(),
    ):
        first = _real_loaded_lmstudio_models(base_url="http://127.0.0.1:1234/v1")
        second = _real_loaded_lmstudio_models(base_url="http://127.0.0.1:1234/v1")

    assert first == second == frozenset({"demo/x"})
    assert call_count["n"] == 1, "second call should hit the cache, not urllib"


def test_invalidate_loaded_cache_forces_fresh_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`invalidate_loaded_cache` makes the next probe re-hit the network.

    The publish flow calls this so a reviewer who manually loads the
    fused model in LM Studio sees the registry row flip from
    `publish_ready` to `published` on the next click, instead of waiting
    up to 30s for the cache to expire.
    """
    from api.services.model_registry import lmstudio_register as _module

    monkeypatch.setattr(
        _module, "loaded_lmstudio_models", _real_loaded_lmstudio_models
    )
    _module.invalidate_loaded_cache()

    call_count = {"n": 0}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            call_count["n"] += 1
            return json.dumps({"data": [{"id": "demo/x"}]}).encode("utf-8")

    with patch(
        "api.services.model_registry.lmstudio_register.urllib.request.urlopen",
        return_value=_Resp(),
    ):
        _real_loaded_lmstudio_models(base_url="http://127.0.0.1:1234/v1")
        _module.invalidate_loaded_cache()
        _real_loaded_lmstudio_models(base_url="http://127.0.0.1:1234/v1")

    assert call_count["n"] == 2, "invalidate must drop the cached entry"
