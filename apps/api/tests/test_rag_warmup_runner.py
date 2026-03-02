import httpx
import pytest

from api.services.rag.warmup_job_runner import run_warmup_job


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: dict[str, object] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"ok": True}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://ollama:11434/v1/embeddings")
            response = httpx.Response(self.status_code, request=request, text='{"error":"model not found"}')
            raise httpx.HTTPStatusError("request failed", request=request, response=response)

    def json(self) -> dict[str, object]:
        return self._payload


def test_run_warmup_job_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_EMBED_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "15")

    calls: list[tuple[str, dict[str, object], float]] = []

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> _FakeResponse:
        calls.append((url, json, timeout))
        return _FakeResponse(status_code=200)

    monkeypatch.setattr("api.services.rag.warmup_job_runner.httpx.post", fake_post)

    result = run_warmup_job()

    assert result["embed_ok"] is True
    assert result["chat_ok"] is True
    assert result["embed_model"] == "nomic-embed-text"
    assert result["chat_model"] == "qwen2.5:7b-instruct-q4_K_M"
    assert result["embed_latency_ms"] >= 0
    assert result["chat_latency_ms"] >= 0

    assert len(calls) == 2
    assert calls[0][0] == "http://ollama:11434/v1/embeddings"
    assert calls[0][1] == {"model": "nomic-embed-text", "input": "hello"}
    assert calls[1][0] == "http://ollama:11434/v1/chat/completions"
    assert calls[1][1]["model"] == "qwen2.5:7b-instruct-q4_K_M"


def test_run_warmup_job_missing_model_error_has_actionable_pull_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_EMBED_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> _FakeResponse:
        del timeout
        request = httpx.Request("POST", url)
        response = httpx.Response(404, request=request, text='{"error":"model not found"}')
        raise httpx.HTTPStatusError("request failed", request=request, response=response)

    monkeypatch.setattr("api.services.rag.warmup_job_runner.httpx.post", fake_post)

    with pytest.raises(RuntimeError) as exc_info:
        run_warmup_job()

    message = str(exc_info.value)
    assert "docker compose exec -T ollama ollama pull nomic-embed-text" in message
    assert "does not auto-pull models" in message


def test_run_warmup_job_connection_error_has_actionable_pull_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_EMBED_BASE_URL", "http://ollama:11434/v1")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    def fake_post(url: str, *, json: dict[str, object], timeout: float) -> _FakeResponse:
        del json, timeout
        request = httpx.Request("POST", url)
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr("api.services.rag.warmup_job_runner.httpx.post", fake_post)

    with pytest.raises(RuntimeError) as exc_info:
        run_warmup_job()

    message = str(exc_info.value)
    assert "docker compose exec -T ollama ollama pull nomic-embed-text" in message
