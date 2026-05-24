from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import Base, get_engine
from api.main import create_app
from api.services import starter_definitions
from api.services.starter_definitions import DEFAULT_STARTER, get_default_starter


def test_default_starter_has_app_and_demo_metadata() -> None:
    starter = get_default_starter()

    assert starter.app.title == "Domain-Adaptable AI Workflow Demo API"
    assert starter.demo.enabled is True
    assert starter.demo.eyebrow
    assert starter.demo.subtitle


def _build_test_client(monkeypatch, tmp_path: Path, *, starter) -> TestClient:
    sqlite_db_path = tmp_path / "starter-tests.db"
    monkeypatch.setenv("API_DATABASE_URL", f"sqlite+pysqlite:///{sqlite_db_path}")
    monkeypatch.setattr(starter_definitions, "DEFAULT_STARTER", starter)
    get_settings.cache_clear()
    get_engine.cache_clear()

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    app = create_app()
    client = TestClient(app)

    original_close = client.close

    def close() -> None:
        original_close()
        engine.dispose()

    client.close = close
    return client


def test_create_app_can_disable_demo(monkeypatch, tmp_path: Path) -> None:
    starter = replace(
        DEFAULT_STARTER, demo=replace(DEFAULT_STARTER.demo, enabled=False)
    )

    with _build_test_client(monkeypatch, tmp_path, starter=starter) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/demo").status_code == 404
        assert client.get("/demo/assets/styles.css").status_code == 404


def test_create_app_renders_demo_from_starter_metadata(
    monkeypatch, tmp_path: Path
) -> None:
    starter = replace(
        DEFAULT_STARTER,
        app=replace(DEFAULT_STARTER.app, title="Custom Skeleton API"),
        demo=replace(
            DEFAULT_STARTER.demo,
            eyebrow="Starter-backed demo",
            subtitle="Rendered from starter metadata.",
        ),
    )

    with _build_test_client(monkeypatch, tmp_path, starter=starter) as client:
        response = client.get("/demo")

    assert response.status_code == 200
    assert "Custom Skeleton API" in response.text
    assert "Starter-backed demo" in response.text
    assert "Rendered from starter metadata." in response.text
