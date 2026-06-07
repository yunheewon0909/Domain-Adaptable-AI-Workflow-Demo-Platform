from __future__ import annotations

import httpx
import pytest

from api.config import get_settings
from api.llm import ChatResult, LLMClientError
from api.services.runtime import (
    OllamaRuntime,
    OpenAICompatRuntime,
    build_chat_runtime,
    build_embedding_runtime,
)


# --- provider selection -------------------------------------------------
def test_default_provider_is_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_RUNTIME_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    get_settings.cache_clear()
    runtime = build_chat_runtime()
    assert isinstance(runtime, OllamaRuntime)
    # Ollama root + OpenAI dialect under /v1.
    assert runtime.native_base_url == "http://ollama:11434"
    assert runtime.base_url == "http://ollama:11434/v1"


def test_openai_compat_provider_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_RUNTIME_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_BASE_URL", "http://host.docker.internal:1234/v1")
    get_settings.cache_clear()
    runtime = build_chat_runtime()
    assert isinstance(runtime, OpenAICompatRuntime)
    assert not isinstance(runtime, OllamaRuntime)
    assert runtime.base_url == "http://host.docker.internal:1234/v1"


def test_lmstudio_envs_are_deprecated_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    """With provider=openai_compat and no LLM_*, the LMSTUDIO_* envs are used."""
    monkeypatch.setenv("LLM_RUNTIME_PROVIDER", "openai_compat")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_CHAT_MODEL", raising=False)
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("LMSTUDIO_CHAT_MODEL", "some-lmstudio-model")
    get_settings.cache_clear()
    runtime = build_chat_runtime()
    assert isinstance(runtime, OpenAICompatRuntime)
    assert runtime.base_url == "http://127.0.0.1:1234/v1"
    assert runtime.default_chat_model == "some-lmstudio-model"


def test_llm_envs_override_lmstudio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_RUNTIME_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_CHAT_MODEL", "preferred-model")
    monkeypatch.setenv("LMSTUDIO_CHAT_MODEL", "ignored-model")
    get_settings.cache_clear()
    runtime = build_chat_runtime()
    assert isinstance(runtime, OpenAICompatRuntime)
    assert runtime.default_chat_model == "preferred-model"


# --- ollama native url construction ------------------------------------
def test_ollama_list_model_ids_uses_api_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = OllamaRuntime(base_url="http://ollama:11434", chat_model="llama3.2")
    captured: dict[str, object] = {}

    def fake_get(url, *, timeout):
        captured["url"] = url
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            request=request,
            json={"models": [{"name": "llama3.2"}, {"name": "nomic-embed-text"}]},
        )

    monkeypatch.setattr("api.services.runtime.ollama.httpx.get", fake_get)
    ids = runtime.list_model_ids()
    assert captured["url"] == "http://ollama:11434/api/tags"
    assert ids == ["llama3.2", "nomic-embed-text"]


def test_openai_compat_list_model_ids_uses_v1_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OpenAICompatRuntime(base_url="http://lmstudio:1234/v1")

    def fake_get(url, *, timeout):
        request = httpx.Request("GET", url)
        assert url == "http://lmstudio:1234/v1/models"
        return httpx.Response(
            200, request=request, json={"data": [{"id": "model-a"}, {"id": "model-b"}]}
        )

    monkeypatch.setattr("api.services.runtime.base.httpx.get", fake_get)
    assert runtime.list_model_ids() == ["model-a", "model-b"]


# --- fake chat ----------------------------------------------------------
def test_runtime_generate_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = OllamaRuntime(base_url="http://ollama:11434", chat_model="llama3.2")
    captured: dict[str, object] = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200, request=request, json={"choices": [{"message": {"content": " hi "}}]}
        )

    monkeypatch.setattr("api.services.runtime.base.httpx.post", fake_post)
    result = runtime.generate_answer(question="q", context="c")
    assert isinstance(result, ChatResult)
    assert result.answer == "hi"
    assert result.model == "llama3.2"
    assert captured["url"] == "http://ollama:11434/v1/chat/completions"


def test_runtime_generate_answer_raises_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = OpenAICompatRuntime(base_url="http://x/v1", chat_model="m")

    def fake_post(url, *, json, timeout):
        request = httpx.Request("POST", url)
        response = httpx.Response(500, request=request, text="boom")
        raise httpx.HTTPStatusError("boom", request=request, response=response)

    monkeypatch.setattr("api.services.runtime.base.httpx.post", fake_post)
    with pytest.raises(LLMClientError, match="boom"):
        runtime.generate_answer(question="q", context="c")


# --- fake embedding -----------------------------------------------------
def test_runtime_embed_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = OllamaRuntime(base_url="http://ollama:11434", embed_model="nomic-embed-text")
    captured: dict[str, object] = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]},
        )

    monkeypatch.setattr("api.services.runtime.base.httpx.post", fake_post)
    vectors = runtime.embed_texts(["a", "b"])
    assert captured["url"] == "http://ollama:11434/v1/embeddings"
    assert captured["payload"] == {"model": "nomic-embed-text", "input": ["a", "b"]}
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_runtime_embed_texts_empty_is_noop() -> None:
    runtime = build_embedding_runtime()
    assert runtime.embed_texts([]) == []
