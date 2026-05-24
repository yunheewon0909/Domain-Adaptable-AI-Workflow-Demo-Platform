from __future__ import annotations

import httpx
import pytest

from api.llm import LLMClientError, LMStudioChatClient


def test_generate_answer_returns_assistant_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LMStudioChatClient(
        base_url="http://127.0.0.1:1234/v1",
        default_model="lmstudio/qwen2.5-7b-instruct-mlx",
        timeout_seconds=30,
    )

    captured: dict[str, object] = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "  hello world  "}}]},
        )

    monkeypatch.setattr("api.llm.httpx.post", fake_post)

    result = client.generate_answer(question="hi", context="ctx")

    assert result.answer == "hello world"
    assert result.model == "lmstudio/qwen2.5-7b-instruct-mlx"
    assert result.used_fallback is False
    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "lmstudio/qwen2.5-7b-instruct-mlx"
    assert payload["temperature"] == 0


def test_generate_answer_raises_llm_client_error_on_http_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LMStudioChatClient(
        base_url="http://127.0.0.1:1234/v1",
        default_model="lmstudio/qwen2.5-7b-instruct-mlx",
        timeout_seconds=30,
    )

    def fake_post(*args, **kwargs):
        request = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")
        response = httpx.Response(500, request=request, text="provider exploded")
        raise httpx.HTTPStatusError(
            "provider exploded", request=request, response=response
        )

    monkeypatch.setattr("api.llm.httpx.post", fake_post)

    with pytest.raises(LLMClientError, match="provider exploded"):
        client.generate_answer(question="hello", context="world")


def test_generate_answer_raises_when_payload_missing_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LMStudioChatClient(
        base_url="http://127.0.0.1:1234/v1",
        default_model="lmstudio/qwen2.5-7b-instruct-mlx",
    )

    def fake_post(url, *, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request, json={"choices": []})

    monkeypatch.setattr("api.llm.httpx.post", fake_post)

    with pytest.raises(LLMClientError, match="missing choices"):
        client.generate_answer(question="hello", context="world")


def test_generate_answer_uses_split_timeout_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LMStudioChatClient(
        base_url="http://127.0.0.1:1234/v1",
        default_model="lmstudio/qwen2.5-7b-instruct-mlx",
        timeout_seconds=600,
    )
    observed: dict[str, object] = {}

    def fake_post(url, *, json, timeout):
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
    timeout = observed["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 5.0
    assert timeout.read == 600
    assert timeout.write == 600
    assert timeout.pool == 5.0


def test_generate_answer_sends_chat_template_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LMStudio body must include `chat_template_kwargs.enable_thinking
    = false` so reasoning-mode models that honor the kwarg (Qwen3, R1) skip
    the thinking pass. Other models silently ignore the unknown kwarg.
    """
    client = LMStudioChatClient(
        base_url="http://127.0.0.1:1234/v1",
        default_model="qwen3.5-4b-mlx",
    )
    captured: dict[str, object] = {}

    def fake_post(url, *, json, timeout):
        captured["payload"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    monkeypatch.setattr("api.llm.httpx.post", fake_post)
    client.generate_answer(question="x", context="y")

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_generate_answer_system_prompt_allows_own_knowledge_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The system prompt was tightened in iteration 6 to let the model
    answer from its own knowledge when no useful context is provided.
    Before the fix, chat-only mode (no rag_collection_id) always
    returned "Context is insufficient." because the prompt told the
    model to "answer using only the provided context".
    """
    client = LMStudioChatClient(
        base_url="http://127.0.0.1:1234/v1",
        default_model="qwen3.5-4b-mlx",
    )
    captured: dict[str, object] = {}

    def fake_post(url, *, json, timeout):
        captured["payload"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "Paris"}}]},
        )

    monkeypatch.setattr("api.llm.httpx.post", fake_post)
    client.generate_answer(question="capital of France?", context="No prior context provided.")

    payload = captured["payload"]
    assert isinstance(payload, dict)
    messages = payload["messages"]
    assert isinstance(messages, list)
    system_msg = next(m for m in messages if m["role"] == "system")
    assert "own knowledge" in system_msg["content"]
    # The old "Answer using only the provided context" prompt is gone.
    assert "using only the provided context" not in system_msg["content"]


def test_generate_answer_raises_actionable_error_on_reasoning_only_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a thinking-mode model exhausts max_tokens during the reasoning
    pass, LM Studio returns empty `content` + populated `reasoning_content`.
    The previous behavior returned the raw reasoning chain as the answer
    (rendering "Thinking Process: 1. Analyze..." to the user). The new
    behavior raises a clear LLMClientError suggesting more tokens.
    """
    client = LMStudioChatClient(
        base_url="http://127.0.0.1:1234/v1",
        default_model="qwen3.5-4b-mlx",
    )

    def fake_post(url, *, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "Thinking Process: 1. Analyze...",
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("api.llm.httpx.post", fake_post)

    with pytest.raises(LLMClientError, match="Increase max_tokens"):
        client.generate_answer(question="hi", context="ctx", max_tokens=64)
