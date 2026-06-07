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


def test_runtime_defaults_to_ollama(monkeypatch) -> None:
    monkeypatch.delenv("LLM_RUNTIME_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_CHAT_MODEL", raising=False)
    monkeypatch.delenv("LMSTUDIO_CHAT_MODEL", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_runtime_provider == "ollama"
    assert settings.llm_base_url == "http://ollama:11434"


def test_runtime_openai_compat_base_url(monkeypatch) -> None:
    monkeypatch.setenv("LLM_RUNTIME_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_BASE_URL", "http://host.docker.internal:1234/v1")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_runtime_provider == "openai_compat"
    assert settings.llm_base_url == "http://host.docker.internal:1234/v1"


def test_lmstudio_envs_are_deprecated_fallbacks(monkeypatch) -> None:
    monkeypatch.setenv("LLM_RUNTIME_PROVIDER", "openai_compat")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_CHAT_MODEL", raising=False)
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LMSTUDIO_CHAT_MODEL", "legacy-model")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_base_url == "http://127.0.0.1:1234/v1"
    assert settings.llm_chat_model == "legacy-model"


def test_unknown_provider_falls_back_to_ollama(monkeypatch) -> None:
    monkeypatch.setenv("LLM_RUNTIME_PROVIDER", "nonsense")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_runtime_provider == "ollama"


def test_numeric_env_falls_back_on_garbage(monkeypatch) -> None:
    """`_to_int` / `_to_float` must not crash on garbage env values."""
    monkeypatch.setenv("RAG_CHUNK_SIZE", "not-a-number")
    monkeypatch.setenv("RAG_CHUNK_OVERLAP", "")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "garbage")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.rag_chunk_size == 500  # documented default
    assert settings.rag_chunk_overlap == 50  # documented default
    assert settings.llm_timeout_seconds == 600.0  # documented default


def test_llm_timeout_seconds_honors_override(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "42.5")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_timeout_seconds == 42.5


def test_llm_timeout_seconds_enforces_minimum(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_timeout_seconds == 1.0
