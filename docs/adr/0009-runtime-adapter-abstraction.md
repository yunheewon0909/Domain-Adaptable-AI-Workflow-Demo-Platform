# ADR 0009: Runtime adapter abstraction

## Status

Accepted (2026-06).

## Context

The codebase hardcoded LM Studio everywhere: `config.py` (`lmstudio_*`), `llm.py`
(`LMStudioChatClient`), `routers/lmstudio.py`, `routers/openai_compat.py`,
`services/model_registry/lmstudio_register.py`, `services/rag/embedding_client.py`, and startup
probes in `main.py`. The Docker-first product defaults to Ollama and must support arbitrary
OpenAI-compatible runtimes without code changes.

## Decision

- Add `apps/api/src/api/services/runtime/` defining `ChatRuntime` and `EmbeddingRuntime`
  protocols.
- Implement `OpenAICompatRuntime` (base; OpenAI `/v1/*` dialect — covers Ollama `/v1`, LM Studio,
  any OpenAI-compatible server) and `OllamaRuntime` (subclass; native `/api/tags` + `/api/embed`).
- Select via config: `LLM_RUNTIME_PROVIDER` (default `ollama`), `LLM_BASE_URL`
  (default `http://ollama:11434`), `LLM_CHAT_MODEL`, `LLM_EMBED_MODEL`.
- Rewire `openai_compat.py`, `llm.py`, and `embedding_client.py` to the adapter. **No router or
  service talks to a runtime directly.**
- Keep `LMSTUDIO_*` env vars as **deprecated aliases** mapping onto `LLM_*` for one release.

## Consequences

- LM Studio becomes one optional provider; Ollama is the default.
- Swapping runtimes is a config change, not a code change.
- Tests fake the adapter rather than a specific vendor's HTTP shape.
