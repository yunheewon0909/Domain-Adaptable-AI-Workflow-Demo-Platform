# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **Docker-first domain RAG + evaluation backend** fronted by **Open WebUI**, with an **Ollama**
container as the default runtime. Upload docs → build a **Graph RAG** knowledge graph → chat with
grounded answers in Open WebUI → generate evaluation testsets and score retrieval/answer quality.
Five containers: `postgres`, `ollama`, `open-webui`, `api`, `worker`. See `README.md` and
`docs/open-webui-docker-migration.md` for the full picture.

> The repo was migrated from a Mac-native MLX QLoRA fine-tuning tool. **Fine-tuning is removed
> from the core** — do not reintroduce it. Do not build a chat UI that competes with Open WebUI
> (`/demo` is an admin/evaluation/debug dashboard only). Do not make LM Studio (or any native
> runtime) required — Docker-only must always be the default path.

## Commands

```bash
# Type check (pyright basic mode is the only configured linter)
uv run pyright -p pyrightconfig.json

# Tests — sqlite-backed, runtime-faked; no Docker/Postgres/Ollama needed
uv run --project apps/api pytest -q apps/api/tests                       # all
uv run --project apps/api pytest -q apps/api/tests/test_runtime.py       # one file
uv run --project apps/api pytest -q "apps/api/tests/test_x.py::test_y"   # one test

# Script syntax checks
bash -n scripts/*.sh ; python -m py_compile scripts/*.py

# Host-side (Docker) — runs on the macOS host, NOT inside AgentDocker
docker compose up -d --build && docker compose ps
```

## Environment: AgentDocker vs host

Development runs inside **AgentDocker**: no host bind mounts, **no host Docker socket**, no
Docker-in-Docker. The Docker daemon is **not reachable here** and **PyYAML is not installed**.
Therefore:

- **AgentDocker-safe** (do these here): repo inspection, `git`, unit tests, `rg` greps,
  `bash -n` / `python -m py_compile`, compose **structure** checks via `rg` (not YAML parsing).
- **Host runtime** (the user runs): `docker compose up`, service health, browser, Open WebUI tool
  import, model pull + inference against Ollama, full E2E. **Never claim host runtime passed
  unless it actually ran** — emit exact host commands + expected signals instead.

## Architecture (the parts that span files)

- **Runtime adapter** (`services/runtime/`): all LLM/embedding calls go through `ChatRuntime` /
  `EmbeddingRuntime`. `OpenAICompatRuntime` (base) covers Ollama `/v1/*`, LM Studio, and any
  OpenAI-compatible endpoint; `OllamaRuntime` adds native `/api/tags` + `/api/embed`. Provider is
  chosen by `LLM_RUNTIME_PROVIDER` (default `ollama`). Never hardcode a provider in routers/services.
- **Worker container**: long jobs (graph indexing, evaluation runs) run in the `worker` container
  via `python -m api.worker`, which runs the same dispatcher loop (`services/background_runner.py`)
  off the shared Postgres **jobs** queue. The API container runs with the dispatcher off
  (`RUN_DISPATCHER=false`). Job types and their runners live in `background_runner._RUNNERS`.
- **Jobs table is the queue + lifecycle source of truth** (`queued → running → succeeded/failed`),
  claimed with `SELECT … FOR UPDATE SKIP LOCKED` on Postgres (asyncio.Lock fallback on sqlite).
- **Graph RAG** (`services/rag/graph_index.py`, `graph_retrieval.py`): Postgres property graph
  (`rag_chunks`/`rag_entities`/`rag_relationships`/`rag_entity_chunks`/`rag_communities`), embeddings
  as JSON with pure-Python cosine, `networkx` for community detection. Retrieval returns a full
  evidence **trace** (`rag_query_traces`) — keep the trace populated; the evaluation phase scores
  against it. pgvector is an optional toggle, not default.
- **Evaluation** (`services/evaluation/`): the old Q/A generator, repurposed to produce reviewable
  `evaluation_questions` linked to source chunks; `evaluation_runs`/`evaluation_results` score
  groundedness + source coverage and produce reports for `/demo` and the Open WebUI tool.
- **OpenAI-compatible shim** (`routers/openai_compat.py`): what Open WebUI points at for chat;
  proxies the configured runtime; supports optional `rag_collection_id` grounding.

### Source layout

`apps/api/src/api/` — `worker.py` (worker entrypoint), `routers/` (rag, evaluation, models,
openai_compat, openwebui, demo, jobs, health), `services/runtime/`, `services/rag/`,
`services/evaluation/`, `static/demo/` (admin dashboard), `static/openwebui/` (importable tool).
Migrations: `apps/api/alembic/versions/`, date-prefixed.

## Conventions

- New routers go under `routers/` and are included in `main.py:create_app`; default seeds run in
  the `lifespan` startup branch.
- Reuse the jobs queue + dispatcher for any new long-running work — one queue, one worker.
- New migrations: date-prefixed under `apps/api/alembic/versions/`.
- All runtime calls go through `services/runtime/` — no direct LM Studio / Ollama HTTP in routers.
- Container images use `python:3.12-slim` (wheel availability); keep code 3.11+ compatible.
- Avoid native-dep graph libraries; `networkx` (pure Python) is the sanctioned graph toolkit.
