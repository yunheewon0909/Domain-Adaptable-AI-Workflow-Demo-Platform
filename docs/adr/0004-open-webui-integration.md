# ADR 0004: Integrate Open WebUI as an optional sidecar rather than vendoring or replacing `/demo`

## Status

Accepted (spike)

## Context

The repo already ships its own reviewer surface at `/demo`, which co-hosts five reviewer modes (Workflow, PLC testing MVP, Fine-tuning, Models, RAG) inside the FastAPI static shell. Open WebUI is a separately maintained chat/model UX that talks to Ollama out of the box and is widely used for local LLM evaluation.

We want to evaluate Open WebUI for chat/model UX comparison without:

- pulling its source into this repo
- coupling its release cadence into our build
- replacing the existing `/demo` reviewer flows that already drive PLC review, training, model registry, and RAG collection management
- creating a second authoritative store for RAG documents, model metadata, or training data

A future evaluation may decide to retire parts of `/demo` in favor of Open WebUI, but this ADR captures the current decision for the spike.

## Decision

Open WebUI is integrated as an **optional Docker Compose sidecar** behind a `open-webui` Compose profile. It runs as its own container, points at the existing `ollama` service via `OLLAMA_BASE_URL=http://ollama:11434`, and keeps its own persistent volume.

Concretely:

- the default `docker compose up` shape is unchanged; no existing reviewer can accidentally start the sidecar
- the sidecar is started with `docker compose --profile open-webui up -d open-webui`
- only Ollama is shared between Open WebUI and our API/worker; Postgres, the model registry, fine-tuning artifacts, RAG collections, PLC suites, and `/demo` are untouched
- no source code of Open WebUI is vendored or submoduled
- no source code in `apps/api` or `apps/worker` is changed for the spike

## Rationale

- a sidecar respects the existing skeleton + domain + AI ops separation documented in ADR 0003
- it lets reviewers compare chat/model UX without forking either project
- it avoids creating cross-store ambiguity (Open WebUI manages its own users, chats, prompts, and RAG; our DB manages model registry, FT datasets, PLC suites, RAG collections)
- it is reversible: removing the sidecar removes the integration, the existing platform keeps working
- Open WebUI itself already speaks to Ollama, so no platform code is needed to make a baseline chat surface work
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

Open WebUI does not read from Postgres, does not see `data/rag_index/`, does not see `data/model_artifacts/`, and does not share authentication with the FastAPI app. Its only inbound dependency is the `ollama` service URL.

## Relation to existing reviewer surfaces

- **`/demo` workflow reviewer**: stays the authoritative reviewer flow for evidence-grounded, model-selectable workflow runs against legacy `rag.db` and collection-managed RAG sources. Open WebUI offers a generic chat path against the same underlying Ollama models; it does not run our workflow validator and does not enforce our degraded-output fallback.
- **`/demo` PLC testing MVP**: not addressed by Open WebUI. PLC suite import, queue-backed runs, deterministic stub executor, validator, and reviewer drill-downs remain the only path.
- **`/demo` Fine-tuning**: unaffected. Open WebUI does not see `ft_datasets`, `ft_dataset_versions`, `ft_dataset_rows`, training jobs, or artifact directories. It cannot enqueue or observe `sft_lora` jobs.
- **`/demo` Models**: still the source of truth for the model registry, artifact-vs-published readiness, and `Use for inference`. Open WebUI lists whatever Ollama exposes locally; it does not respect artifact-only readiness gating, so it should not be presented as a substitute for the Models tab.
- **`/demo` RAG**: stays authoritative for `rag_collections` and `rag_documents`. Open WebUI ships its own RAG ingestion pipeline that writes into its own store; treating the two stores as equivalent is explicitly out of scope.

## Future path: optional OpenAI-compatible shim

If we later decide to let Open WebUI (or other external chat clients) reach our model-registry-aware inference path instead of going directly to Ollama, the natural extension is a thin OpenAI-compatible shim exposed by `apps/api`, e.g.:

- `GET /v1/models` returning serving-ready selectable registry rows only
- `POST /v1/chat/completions` adapting to our `/inference/run` semantics, including readiness gating and (optionally) RAG-collection-grounded context

This shim is **not implemented as part of this spike**. It is intentionally deferred until we know whether Open WebUI is the right consumer for it, because:

- the value depends on enforcing model-registry readiness through external clients
- we want to avoid introducing a second inference surface before the spike validates that an external UI is even desirable

If the spike confirms the direction, the shim can land in a follow-up milestone without touching the sidecar wiring.

## Pros

- zero source coupling; upgrading Open WebUI is a tag bump on a public image
- default stack behavior is unchanged; reviewers without the profile see no difference
- side-by-side comparison is cheap (one container, one volume)
- removes the temptation to rebuild a generic chat UI inside `/demo`
- keeps the existing milestone language (`/demo` still spans five reviewer modes) accurate

## Cons / risks

- **data store separation**: Open WebUI has its own users, chats, prompts, and RAG store; reviewers may mistakenly assume documents uploaded into Open WebUI are visible to our `rag_collections` or workflow evidence path, which is not true
- **readiness gating bypass**: Open WebUI talks to Ollama directly, so it will surface any model present in Ollama regardless of our `model_registry` `artifact_ready` vs `published` policy; reviewers must not treat its model list as authoritative
- **auth**: Open WebUI manages its own auth (signup on first run by default); this repo has no auth and the sidecar should not be assumed to share identity with `/demo`
- **license/branding**: Open WebUI is third-party software with its own license and brand. We are not redistributing it; we reference a public image. Any decision to bundle, fork, or rebrand it would require a separate review of upstream license terms before action.
- **port collision**: the default mapping is `3000:8080`; reviewers running other tools on `3000` need to override `OPEN_WEBUI_PORT`
- **first-run downloads**: the Open WebUI image is non-trivial in size and will pull on first `up`; this is a one-time cost
- **expectation drift**: reviewers may interpret the sidecar as a commitment to migrate `/demo`; this ADR explicitly does not commit to that and any migration would be a separate decision

## Consequences

- this repo gains an optional, removable evaluation surface without altering any existing reviewer flow
- the platform retains a single source of truth for registry, training, RAG collections, PLC suites, and queue lifecycle
- a future ADR can revisit either an OpenAI-compatible shim or a reviewer surface migration, with the evidence from this spike to support the call
