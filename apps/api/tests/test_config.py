from api.config import get_settings


def test_rag_chunk_defaults(monkeypatch) -> None:
    monkeypatch.delenv("RAG_CHUNK_SIZE", raising=False)
    monkeypatch.delenv("RAG_CHUNK_OVERLAP", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.rag_chunk_size == 500
    assert settings.rag_chunk_overlap == 50


def test_rag_chunk_overrides(monkeypatch) -> None:
    monkeypatch.setenv("RAG_CHUNK_SIZE", "1024")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "128")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.rag_chunk_size == 1024
    assert settings.rag_chunk_overlap == 128


def test_lmstudio_defaults(monkeypatch) -> None:
    monkeypatch.delenv("LMSTUDIO_BASE_URL", raising=False)
    monkeypatch.delenv("LMSTUDIO_CHAT_MODEL", raising=False)
    monkeypatch.delenv("LMSTUDIO_EMBED_MODEL", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.lmstudio_base_url == "http://localhost:1234/v1"
    assert settings.lmstudio_chat_model == ""
    assert settings.lmstudio_embed_model == ""


def test_numeric_env_falls_back_on_garbage(monkeypatch) -> None:
    """`_to_int` / `_to_float` must not crash on garbage env values.

    Reviewers who typo a numeric env (e.g. `LMSTUDIO_TIMEOUT_SECONDS=auto`)
    used to take down the API process at boot. The hardened helpers
    silently fall back to the documented default instead.
    """
    monkeypatch.setenv("RAG_CHUNK_SIZE", "not-a-number")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "")
    monkeypatch.setenv("LMSTUDIO_TIMEOUT_SECONDS", "garbage")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.rag_chunk_size == 500  # documented default
    assert settings.rag_chunk_overlap == 50  # documented default
    assert settings.lmstudio_timeout_seconds == 600.0  # documented default


def test_lmstudio_timeout_seconds_honors_override(monkeypatch) -> None:
    monkeypatch.setenv("LMSTUDIO_TIMEOUT_SECONDS", "42.5")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.lmstudio_timeout_seconds == 42.5


def test_lmstudio_timeout_seconds_enforces_minimum(monkeypatch) -> None:
    """Negative or sub-1.0 timeouts would break httpx; clamp to the minimum."""
    monkeypatch.setenv("LMSTUDIO_TIMEOUT_SECONDS", "0")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.lmstudio_timeout_seconds == 1.0


def test_ft_trainer_model_map_default_includes_qwen_mlx(monkeypatch) -> None:
    """The demo's Train button enqueues `qwen3.5-4b-mlx` jobs without
    setting trainer_model_name; the default map must resolve that to a
    tiny MLX checkpoint so the trainer subprocess can download it.
    """
    monkeypatch.delenv("FT_TRAINER_MODEL_MAP_JSON", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    import json as _json

    parsed = _json.loads(settings.ft_trainer_model_map_json)
    assert parsed.get("qwen3.5-4b-mlx") == "mlx-community/Qwen2.5-0.5B-Instruct-4bit"


def test_mlx_model_namespace_defaults_to_demo(monkeypatch) -> None:
    """Required so `build_publish_manifest` produces a candidate_model_name
    out of the box; otherwise publish always 409s.
    """
    monkeypatch.delenv("MLX_MODEL_NAMESPACE", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.mlx_model_namespace == "demo"
