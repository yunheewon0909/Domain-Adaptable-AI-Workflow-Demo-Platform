# Domain-Adaptable AI Workflow Demo Platform

## Overview

This repository packages a small local demo platform that combines:

- a FastAPI service
- a background worker with a Postgres-backed job queue
- local retrieval over SQLite and JSON fallback artifacts
- Ollama-backed chat and embedding models
- a co-hosted `/demo` UI for reviewer workflows

The main reviewer path is a single page where you choose a dataset, run one of three fixed workflows, and inspect structured output with mandatory evidence.

## Phase 1 Scope

Implemented in the current phase:

- dataset registry with active dataset selection
- workflow catalog with exactly three workflows:
  - `briefing`
  - `recommendation`
  - `report_generator`
- workflow jobs stored as `type=workflow_run`
- retrieval-first typed outputs with mandatory `evidence[]`
- retained `/rag/search` and `/ask` APIs
- retained operational jobs:
  - `/rag/warmup`
  - `/rag/verify`
  - `/rag/reindex`
- a co-hosted `/demo` page for end-to-end review

Out of scope:

- multi-user auth
- dataset upload pipelines
- generalized dataset versioning
- Kubernetes packaging
- a separate web frontend app

## Architecture

Runtime services:

- `postgres`: stores jobs, worker heartbeats, and datasets
- `api`: FastAPI service with workflow, jobs, dataset, and RAG endpoints
- `worker`: polls jobs and runs operational or workflow subprocesses
- `ollama`: serves chat and embedding models

Primary data paths:

- default industrial dataset:
  - source: `data/sample_docs`
  - index: `data/rag_index`
  - sqlite db: `data/rag_index/rag.db`
- secondary enterprise dataset:
  - source: `data/datasets/enterprise_docs/source`
  - index: `data/datasets/enterprise_docs/index`
  - sqlite db: `data/datasets/enterprise_docs/index/rag.db`

## Requirements

- Docker
- Docker Compose
- `uv`
- optional: `jq` for easier CLI inspection

## Quick Start With Docker Compose

1. Create the persistent Ollama model volume once.

```bash
docker volume create ollama-models || true
```

2. Start the local stack.

```bash
docker compose up -d --build
docker compose ps
```

Expected result: `api`, `worker`, `postgres`, and `ollama` are up.

3. Pull the required models on first run.

```bash
docker compose exec -T ollama ollama pull qwen2.5:3b-instruct-q4_K_M
docker compose exec -T ollama ollama pull qwen2.5:7b-instruct-q4_K_M
docker compose exec -T ollama ollama pull nomic-embed-text
```

4. Check the core routes.

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/datasets
curl -s http://127.0.0.1:8000/workflows
curl -s http://127.0.0.1:8000/demo | head
```

Expected result:

- `/health` returns `{"status":"ok"}`
- `/datasets` returns `industrial_demo` and `enterprise_docs`
- `/workflows` returns the fixed workflow catalog
- `/demo` serves the static reviewer UI

5. Switch the active dataset.

```bash
curl -sS -X POST http://127.0.0.1:8000/datasets/active \
  -H "Content-Type: application/json" \
  -d '{"dataset_key":"enterprise_docs"}'

curl -s http://127.0.0.1:8000/datasets
```

6. Enqueue a workflow job.

```bash
curl -sS -X POST http://127.0.0.1:8000/workflows/briefing/jobs \
  -H "Content-Type: application/json" \
  -d '{"dataset_key":"enterprise_docs","prompt":"Prepare a reviewer briefing for this dataset.","k":4}'
```

Expected result: `202` with `job_id`, `status`, `workflow_key`, and `dataset_key`.

7. Inspect the job result.

```bash
curl -sS http://127.0.0.1:8000/jobs/<job_id>
curl -sS "http://127.0.0.1:8000/jobs?workflow_key=briefing&dataset_key=enterprise_docs"
```

Important note: the worker may claim jobs quickly, so `status=queued` filters can legitimately return an empty array. For verification, prefer `GET /jobs/<job_id>` or a workflow-plus-dataset filter without `status`.

8. Check the retrieval endpoints.

```bash
curl -sG "http://127.0.0.1:8000/rag/search" \
  --data-urlencode "q=workflow evidence" \
  --data-urlencode "k=2" \
  --data-urlencode "dataset_key=enterprise_docs"

curl -s -X POST "http://127.0.0.1:8000/ask" \
  -H "Content-Type: application/json" \
  -d '{"question":"What should a reviewer focus on?","k":2,"dataset_key":"enterprise_docs"}'
```

Expected result:

- `/rag/search` returns `chunk_id`, `source_path`, `title`, `score`, and `text`
- `/ask` returns `answer`, `sources`, and `meta`

9. Check the operational jobs.

```bash
curl -sS -X POST http://127.0.0.1:8000/rag/warmup
curl -sS -X POST http://127.0.0.1:8000/rag/verify
curl -sS -X POST "http://127.0.0.1:8000/rag/reindex?mode=incremental"
curl -sS -X POST "http://127.0.0.1:8000/rag/reindex?mode=full"
```

Each request should return a queued job. Inspect them with `GET /jobs/<job_id>`.

10. Tail worker logs when you want live execution evidence.

```bash
docker compose logs -f --tail=200 worker
```

11. Stop the stack when you are done.

```bash
docker compose down
```

## Host-Only Run

If you want to run without Docker Compose, start Postgres and Ollama separately, then use:

```bash
export API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai

uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000
```

In another shell:

```bash
export WORKER_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai
export WORKER_ID=worker-local
export WORKER_HEARTBEAT_SECONDS=30
export WORKER_POLL_SECONDS=5
export JOB_MAX_ATTEMPTS=3
export WORKER_API_PROJECT_DIR=/workspace/apps/api

uv run --project apps/worker python -m worker.main
```

## Demo UI

Open:

```text
http://127.0.0.1:8000/demo
```

The page supports:

- dataset selection
- workflow selection
- prompt entry
- automatic polling of job status
- typed result rendering
- evidence card rendering

The UI currently renders three result shapes:

- `briefing`: `summary`, `key_points`, `evidence`
- `recommendation`: `recommendations`, `rationale`, `evidence`
- `report_generator`: `title`, `executive_summary`, `findings`, `actions`, `evidence`

## API Summary

Core routes:

- `GET /health`
- `GET /datasets`
- `POST /datasets/active`
- `GET /workflows`
- `POST /workflows/{workflow_key}/jobs`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /rag/search`
- `POST /ask`
- `POST /rag/warmup`
- `POST /rag/verify`
- `POST /rag/reindex`
- `GET /demo`

Job transitions:

- `queued -> running -> succeeded`
- `queued -> running -> failed`

Useful filters:

```bash
curl -sS "http://127.0.0.1:8000/jobs?workflow_key=report_generator&dataset_key=enterprise_docs"
curl -sS "http://127.0.0.1:8000/jobs?type=rag_reindex_incremental"
curl -sS "http://127.0.0.1:8000/jobs?status=succeeded"
```

## Testing

Install workspace dependencies:

```bash
uv sync --dev
```

Run static checks:

```bash
uv run pyright -p pyrightconfig.json
```

Run API tests:

```bash
uv run --project apps/api pytest -q apps/api/tests
```

Run worker tests:

```bash
uv run --project apps/worker pytest -q apps/worker/tests
```

Each project now configures `pytest` with `pythonpath = ["src"]`, so these commands work directly from the repository root.

## Project Guide

- `apps/api/src/api/main.py`: app assembly and startup seeding
- `apps/api/src/api/routers/`: route handlers for datasets, workflows, jobs, demo, rag, and health
- `apps/api/src/api/services/datasets/`: dataset registry and resolver
- `apps/api/src/api/services/workflows/`: workflow catalog, contracts, profiles, execution, and job runner
- `apps/api/src/api/services/retrieval/service.py`: dataset-aware evidence retrieval and grounding context
- `apps/api/src/api/static/demo/`: co-hosted demo UI assets
- `apps/worker/src/worker/main.py`: worker loop and subprocess dispatch
- `data/sample_docs`: default industrial dataset source
- `data/rag_index`: default industrial dataset runtime index
- `data/datasets/enterprise_docs`: secondary demo dataset source and index artifacts

## Current Validation Status

The current repository state has been verified for:

- `pyright`
- API tests
- worker tests
- Compose startup
- dataset switching
- all three workflow types
- `/demo` UI workflow execution
- `/rag/search`
- `/ask`
- `/rag/warmup`
- `/rag/verify`
- `/rag/reindex?mode=incremental`
- `/rag/reindex?mode=full`

Non-blocking warnings remain from:

- FastAPI `on_event` deprecation
- Alembic `path_separator` deprecation warning

These warnings do not currently block local execution or test success.
