from __future__ import annotations

import httpx
import pytest

from api.llm import LLMClientError, OllamaChatClient


def test_generate_answer_raises_last_provider_error_when_requested_model_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OllamaChatClient(
        base_url="http://ollama:11434/v1",
        default_model="qwen2.5:7b-instruct-q4_K_M",
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
        default_model="qwen2.5:7b-instruct-q4_K_M",
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

    assert calls == ["qwen2.5:7b-instruct-q4_K_M", "qwen2.5:3b-instruct-q4_K_M"]
