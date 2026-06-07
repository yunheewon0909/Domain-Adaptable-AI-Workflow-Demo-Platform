from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import Base, get_engine
from api.main import app


@pytest.fixture(autouse=True)
def reset_api_caches(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Deterministic runtime config for tests. The runtime is never actually
    # reached over HTTP (tests override dependencies or fall back to lexical
    # retrieval offline), but a configured embed model exercises the embed path.
    monkeypatch.setenv("LLM_RUNTIME_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("LLM_CHAT_MODEL", "llama3.2")
    monkeypatch.delenv("LLM_EMBED_MODEL", raising=False)
    # Background dispatcher stays off in tests; the worker container runs it in
    # the real deployment.
    monkeypatch.setenv("FT_BACKGROUND_DISPATCH", "false")
    get_settings.cache_clear()
    get_engine.cache_clear()

    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    sqlite_db_path = tmp_path / "api-tests.db"
    monkeypatch.setenv("API_DATABASE_URL", f"sqlite+pysqlite:///{sqlite_db_path}")
    monkeypatch.setenv("API_DB_ECHO", "false")

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as test_client:
        yield test_client

    engine.dispose()
