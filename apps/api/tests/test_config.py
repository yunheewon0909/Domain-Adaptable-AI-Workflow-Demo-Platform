from api.config import get_settings


def test_rag_db_path_uses_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("RAG_INDEX_DIR", "data/custom-index")
    monkeypatch.setenv("RAG_DB_PATH", "data/override/r4.db")

    settings = get_settings()

    assert settings.rag_index_dir == "data/custom-index"
    assert settings.rag_db_path == "data/override/r4.db"


def test_rag_db_path_defaults_to_index_dir(monkeypatch) -> None:
    monkeypatch.setenv("RAG_INDEX_DIR", "data/custom-index")
    monkeypatch.delenv("RAG_DB_PATH", raising=False)

    settings = get_settings()

    assert settings.rag_db_path.endswith("data/custom-index/rag.db")


def test_rag_expected_embed_dim_defaults_and_can_disable(monkeypatch) -> None:
    monkeypatch.delenv("RAG_EXPECTED_EMBED_DIM", raising=False)
    settings = get_settings()
    assert settings.rag_expected_embed_dim == 768

    get_settings.cache_clear()
    monkeypatch.setenv("RAG_EXPECTED_EMBED_DIM", "0")
    settings = get_settings()
    assert settings.rag_expected_embed_dim == 0


def test_rag_verify_sample_query_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("RAG_VERIFY_SAMPLE_QUERY", raising=False)
    settings = get_settings()
    assert settings.rag_verify_sample_query == "maintenance automation"

    get_settings.cache_clear()
    monkeypatch.setenv("RAG_VERIFY_SAMPLE_QUERY", "quality inspection")
    settings = get_settings()
    assert settings.rag_verify_sample_query == "quality inspection"
