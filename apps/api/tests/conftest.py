from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import Base, get_engine
from api.main import app


@pytest.fixture(autouse=True)
def reset_api_caches(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Default LM Studio chat model so ensure_default_models seeds the registry
    # in tests that depend on a default selectable entry.
    monkeypatch.setenv("LMSTUDIO_CHAT_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    # Background dispatcher must stay off in tests to prevent the real trainer
    # subprocess from racing with TestClient calls.
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
