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
