# ADR 0004: Integrate Open WebUI as an optional sidecar rather than vendoring or replacing `/demo`

## Status

Accepted (sidecar + platform-shim integration)

## Context

The repo already ships its own reviewer surface at `/demo`, which co-hosts five reviewer modes (Workflow, PLC testing MVP, Fine-tuning, Models, RAG) inside the FastAPI static shell. Open WebUI is a separately maintained chat/model UX that talks to Ollama out of the box and is widely used for local LLM evaluation.

We want to evaluate Open WebUI for chat/model UX comparison without:

- pulling its source into this repo
- coupling its release cadence into our build
- replacing the existing `/demo` reviewer flows that already drive PLC review, training, model registry, and RAG collection management
- creating a second authoritative store for RAG documents, model metadata, or training data

A future evaluation may decide to retire parts of `/demo` in favor of Open WebUI, but this ADR captures the current decision for the spike.

## Decision

Open WebUI is integrated as an **optional Docker Compose sidecar** behind a `open-webui` Compose profile. It runs as its own container, points at the FastAPI platform's OpenAI-compatible shim at `http://api:8000/v1`, disables direct Ollama model listing, and keeps its own persistent volume. Ollama remains the shared runtime behind the API/worker, but Open WebUI should see registry-gated platform models rather than raw Ollama duplicates.

Concretely:

- the default `docker compose up` shape is unchanged; no existing reviewer can accidentally start the sidecar
- the sidecar is started with `docker compose --profile open-webui up -d open-webui`
- Open WebUI is started with `ENABLE_OLLAMA_API=False` and `OPENAI_API_BASE_URLS=http://api:8000/v1`
- the API shim exposes only runtime-ready/selectable model-registry rows through `/v1/models`
- a repo-owned importable Open WebUI Tool artifact (`/openwebui/platform_tools.py`) lets chats call platform RAG collections and workflow jobs without forking Open WebUI
- no source code of Open WebUI is vendored or submoduled
- Open WebUI still owns its users, chats, prompts, and uploads; it does not become the source of truth for platform RAG, training, PLC, or registry state

## Rationale

- a sidecar respects the existing skeleton + domain + AI ops separation documented in ADR 0003
- it lets reviewers compare chat/model UX without forking either project
- it avoids creating cross-store ambiguity (Open WebUI manages its own users, chats, prompts, and RAG; our DB manages model registry, FT datasets, PLC suites, RAG collections)
- it is reversible: removing the sidecar removes the integration, the existing platform keeps working
- Open WebUI itself can speak to Ollama, but direct Ollama exposure produces duplicate raw models and bypasses platform readiness policy
- the shim keeps chat UX inside the platform's model-registry/readiness boundary while still avoiding an Open WebUI fork
- splitting evaluation from adoption keeps milestone risk low: we can observe usage before committing to replacing any reviewer surface

## Architecture sketch

```
                       ┌────────────────────────────────────┐
                       │           ollama (shared)          │
                       │     models + embeddings runtime    │
                       └───────────────┬────────────────────┘
                                       │ http://ollama:11434
                       ┌───────────────┴────────────────────┐
                       │                                    │
              ┌────────▼─────────┐               ┌──────────▼────────┐
              │  api (FastAPI)   │               │   open-webui      │
              │  /demo, /models, │               │  separate UI,     │
              │  /workflows,     │               │  own data volume, │
              │  /rag-*, /plc-*  │               │  own auth/users   │
              └────────┬─────────┘               └───────────────────┘
                       │
              ┌────────▼─────────┐
              │     worker       │
              │  PLC + FT jobs   │
              └────────┬─────────┘
                       │
              ┌────────▼─────────┐
              │    postgres      │
              │  jobs + domain   │
              └──────────────────┘
```

Open WebUI does not read from Postgres, does not see `data/rag_index/`, does not see `data/model_artifacts/`, and does not share authentication with the FastAPI app. Its primary model dependency is the API shim; the API/worker continue to use Ollama behind the platform boundary.

## Relation to existing reviewer surfaces

- **`/demo` workflow reviewer**: stays the authoritative reviewer flow for evidence-grounded, model-selectable workflow runs against legacy `rag.db` and collection-managed RAG sources. Open WebUI offers a generic chat path against the same underlying Ollama models; it does not run our workflow validator and does not enforce our degraded-output fallback.
- **`/demo` PLC testing MVP**: not addressed by Open WebUI. PLC suite import, queue-backed runs, deterministic stub executor, validator, and reviewer drill-downs remain the only path.
- **`/demo` Fine-tuning**: unaffected. Open WebUI does not see `ft_datasets`, `ft_dataset_versions`, `ft_dataset_rows`, training jobs, or artifact directories. It cannot enqueue or observe `sft_lora` jobs.
- **`/demo` Models**: still the source of truth for the model registry, artifact-vs-published readiness, and `Use for inference`. Open WebUI now reaches models through `/v1/models`, so it should show only runtime-ready/selectable platform rows rather than whatever raw models happen to exist in Ollama.
- **`/demo` RAG**: stays authoritative for `rag_collections` and `rag_documents`. The shim can accept an optional `rag_collection_id` for platform-managed grounding, but stock Open WebUI chats do not yet send that field; a tool/function/custom request layer is still needed for user-selectable platform RAG inside Open WebUI.

## OpenAI-compatible shim

The sidecar now uses a thin OpenAI-compatible shim exposed by `apps/api`:

- `GET /v1/models` returns serving-ready selectable registry rows only, with human-readable model ids and internal `registry_id` metadata
- `POST /v1/chat/completions` adapts to our `LLMClient` semantics, including readiness gating, compatibility SSE streaming, and optional `rag_collection_id` / `top_k` context grounding

This keeps external chat clients from bypassing the artifact-only vs published distinction. The shim deliberately remains small: no true token streaming and no general OpenAI tool/function-calling implementation. Platform RAG/workflow calls are handled through the separate importable Open WebUI Tool artifact.

## Open WebUI platform tool

`/openwebui/platform_tools.py` serves a small Open WebUI Tool module that can be imported into the sidecar. It defaults to `http://api:8000` and exposes functions to list/query platform RAG collections, list workflows, enqueue workflow jobs, and read job status. This keeps user-facing chat affordances in Open WebUI while preserving the platform API as the source of truth for RAG/workflow state.

## Pros

- zero source coupling; upgrading Open WebUI is a tag bump on a public image
- default stack behavior is unchanged; reviewers without the profile see no difference
- side-by-side comparison is cheap (one container, one volume)
- removes the temptation to rebuild a generic chat UI inside `/demo`
- keeps the existing milestone language (`/demo` still spans five reviewer modes) accurate

## Cons / risks

- **data store separation**: Open WebUI has its own users, chats, prompts, and RAG store; reviewers may mistakenly assume documents uploaded into Open WebUI are visible to our `rag_collections` or workflow evidence path, which is not true. Use the platform tool when a chat needs platform-managed RAG/workflow state.
- **configuration drift**: if direct Ollama is manually re-enabled in Open WebUI admin settings, it can again surface raw duplicate models and bypass the `model_registry` `artifact_ready` vs `published` policy
- **auth**: Open WebUI manages its own auth (signup on first run by default); this repo has no auth and the sidecar should not be assumed to share identity with `/demo`
- **license/branding**: Open WebUI is third-party software with its own license and brand. We are not redistributing it; we reference a public image. Any decision to bundle, fork, or rebrand it would require a separate review of upstream license terms before action.
- **port collision**: the default mapping is `3000:8080`; reviewers running other tools on `3000` need to override `OPEN_WEBUI_PORT`
- **first-run downloads**: the Open WebUI image is non-trivial in size and will pull on first `up`; this is a one-time cost
- **expectation drift**: reviewers may interpret the sidecar as a commitment to migrate `/demo`; this ADR explicitly does not commit to that and any migration would be a separate decision

## Consequences

- this repo gains an optional, removable evaluation surface without altering any existing reviewer flow
- the platform retains a single source of truth for registry, training, RAG collections, PLC suites, and queue lifecycle
- Open WebUI becomes a plausible user-facing chat shell for registry-gated models, while `/admin` remains the internal/operator console for workflows, RAG collection management, training, PLC, and review state
- a future ADR can revisit reviewer-surface migration or deeper Open WebUI automation, with the evidence from this integration to support the call
