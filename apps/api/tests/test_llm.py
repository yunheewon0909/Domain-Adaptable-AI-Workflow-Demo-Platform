from __future__ import annotations

import httpx
import pytest

from api.llm import LLMClientError, OllamaChatClient


def test_generate_answer_raises_last_provider_error_when_requested_model_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OllamaChatClient(
        base_url="http://ollama:11434/v1",
        default_model="qwen3.5:4b",
        fallback_model="qwen2.5:3b-instruct-q4_K_M",
        timeout_seconds=30,
    )

    def fake_post(*args, **kwargs):
        request = httpx.Request("POST", "http://ollama:11434/v1/chat/completions")
        response = httpx.Response(500, request=request, text="provider exploded")
        raise httpx.HTTPStatusError(
            "provider exploded", request=request, response=response
        )

    monkeypatch.setattr("api.llm.httpx.post", fake_post)

    with pytest.raises(LLMClientError, match="provider exploded"):
        client.generate_answer(
            question="hello",
            context="world",
            model="qwen2.5:3b-instruct-q4_K_M",
        )


def test_generate_answer_raises_fallback_error_when_all_candidates_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OllamaChatClient(
        base_url="http://ollama:11434/v1",
        default_model="qwen3.5:4b",
        fallback_model="qwen2.5:3b-instruct-q4_K_M",
        timeout_seconds=30,
    )

    calls: list[str] = []

    def fake_post(url, *, json, timeout):
        model = json["model"]
        calls.append(model)
        request = httpx.Request("POST", url)
        response = httpx.Response(500, request=request, text=f"{model} failed")
        raise httpx.HTTPStatusError(
            f"{model} failed", request=request, response=response
        )

    monkeypatch.setattr("api.llm.httpx.post", fake_post)

    with pytest.raises(LLMClientError, match="qwen2.5:3b-instruct-q4_K_M failed"):
        client.generate_answer(question="hello", context="world")

    assert calls == ["qwen3.5:4b", "qwen2.5:3b-instruct-q4_K_M"]


def test_generate_answer_uses_read_timeout_budget_for_slow_local_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OllamaChatClient(
        base_url="http://ollama:11434/v1",
        default_model="qwen3.5:4b",
        fallback_model="qwen2.5:3b-instruct-q4_K_M",
        timeout_seconds=600,
    )
    observed: dict[str, object] = {}

    def fake_post(url, *, json, timeout):
        observed["payload"] = json
        observed["timeout"] = timeout
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    monkeypatch.setattr("api.llm.httpx.post", fake_post)

    result = client.generate_answer(question="hello", context="world")

    assert result.answer == "ok"
    assert observed["payload"]["reasoning"] == {"effort": "none"}
    timeout = observed["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 5.0
    assert timeout.read == 600
    assert timeout.write == 600
    assert timeout.pool == 5.0
