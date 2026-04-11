# Domain-Adaptable AI Workflow Demo Platform

## Overview

This repository is now positioned as an extensible monorepo-style skeleton for domain-adaptable AI and automation services. It still ships the original reviewer workflow demo, but it now also includes an MVP for **DB-centered PLC test automation** that imports Excel/CSV test suites, queues deterministic runs, records pass/fail and raw I/O, and exposes results through API plus a co-hosted reviewer UI.

The key message of the repo is now twofold:

- **skeleton/demo**: a reviewer-friendly starter with FastAPI, worker, Postgres queue, and co-hosted static UI
- **domain service**: a concrete PLC testing slice that shows how Excel-based industrial test assets can be turned into a DB + queue + dashboard workflow without overhauling the skeleton

## What the PLC Testing MVP Adds

The new PLC slice focuses on this problem: LS PLC testcases often start life in spreadsheets, while actual write/read behavior already lives in existing execution assets such as C++ scripts. This MVP turns those spreadsheet-defined cases into a database-backed suite, runs them through the existing worker queue, and stores deterministic verdicts and execution traces in a reviewable form.

Included in the current MVP:

- CSV and XLSX suite import
- normalization of spreadsheet rows into runnable testcase records
- database-backed suite storage
- `plc_test_run` jobs on the existing `jobs` queue
- deterministic stub PLC executor
- future C++ CLI adapter seam using subprocess + JSON
- exact-match validator with explicit failure reasons
- run/result APIs for suite-level and testcase-level review
- dashboard summary API for recent runs, queue stats, and failure hotspots
- expanded `/demo` reviewer surface for PLC import, run, and drill-down

Out of scope for this MVP:

- real PLC hardware control
- authentication and permissions
- cancel/retry UI for PLC runs
- fully normalized PLC case/result tables
- live progress streaming beyond queue polling
- LLM-driven execution or pass/fail decisions

## Architecture Summary

### Runtime services

- `postgres`: queue and application metadata
- `api`: FastAPI app, routers, domain services, static demo UI, runner modules
- `worker`: Postgres-backed job worker that dispatches runner modules via subprocess
- `ollama`: local LLM/embedding runtime for the original reviewer workflows

### PLC execution path

1. Upload CSV/XLSX via `POST /plc-testcases/import`
2. Normalize rows into one stored PLC suite in `plc_test_suites`
3. Enqueue a `plc_test_run` job with `POST /plc-test-runs`
4. Worker claims the queued job from the existing `jobs` table
5. Worker runs `api.services.plc.job_runner` via subprocess
6. Runner executes a deterministic stub executor or future CLI adapter
7. Validator records pass/fail and testcase-level detail into `jobs.result_json`
8. Reviewer UI and APIs read the same stored result payload back

### Deterministic execution rules

- The **executor is not LLM-controlled**
- The **validator is rule-based exact match**
- A testcase mismatch is stored as a **failed testcase inside a succeeded run job**
- A parsing/runtime/infrastructure problem produces a **failed job**

That separation keeps the queue lifecycle stable while making business-level test failures reviewable instead of infrastructural.

## Repo Structure

```text
repo/
├─ apps/
│  ├─ api/                    # HTTP surface, static /demo UI, domain services, runner modules
│  └─ worker/                 # queue polling, retry logic, subprocess dispatch
├─ data/                      # sample reviewer datasets and local retrieval artifacts
├─ docs/
│  ├─ architecture.md
│  ├─ skeleton-vs-service.md
│  └─ adr/
├─ shared/                    # shared-core seam placeholder and role documentation
├─ CHANGELOG.md
├─ compose.yml
├─ pyproject.toml             # uv workspace root
└─ README.md
```

### Responsibility split

- **skeleton**: workspace layout, FastAPI app, worker, queue pattern, static reviewer shell
- **demo/reviewer**: `/demo` UI used to review both workflow and PLC slices
- **service/domain**: `apps/api/src/api/services/plc/` plus related routers/migrations/tests
- **shared core**: `shared/` as the reserved place for framework-agnostic seams and docs, without forcing a premature package split

This repo intentionally uses **directory separation instead of long-lived branches** to show how demo and service code can coexist inside one expandable monorepo skeleton.

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

3. Pull the required models on first run for the original workflow reviewer flow.

```bash
docker compose exec -T ollama ollama pull qwen2.5:3b-instruct-q4_K_M
docker compose exec -T ollama ollama pull qwen2.5:7b-instruct-q4_K_M
docker compose exec -T ollama ollama pull nomic-embed-text
```

4. Run migrations.

```bash
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
```

5. Check the core routes.

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/workflows
curl -s http://127.0.0.1:8000/plc-dashboard/summary
curl -s http://127.0.0.1:8000/demo
```

## Host-Only Run

API:

```bash
export API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai
export OLLAMA_TIMEOUT_SECONDS=120
export PLC_EXECUTOR_MODE=stub

uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Worker:

```bash
export WORKER_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai
export WORKER_ID=worker-local
export WORKER_HEARTBEAT_SECONDS=30
export WORKER_POLL_SECONDS=5
export JOB_MAX_ATTEMPTS=3
export WORKER_API_PROJECT_DIR="$(pwd)/apps/api"
export PLC_EXECUTOR_MODE=stub

uv run --project apps/worker python -m worker.main
```

## PLC Import Example

Example CSV columns:

- `instruction_name`
- `input_values`
- `expected_outputs`
- `input_type`
- `output_type`
- optional: `description`, `tags`, `memory_profile_key`, `timeout_ms`, `expected_outcome`, `case_key`

Example row that expands into multiple testcases:

```csv
instruction_name,input_values,expected_outputs,input_type,output_type,description,tags,memory_profile_key
add,"[[1,1],[2,2],[4,4]]","[2,4,8]",LWORD,LWORD,adder,"smoke,math",ls_add_lword_v1
```

Import it:

```bash
curl -sS -X POST http://127.0.0.1:8000/plc-testcases/import \
  -F "title=LS Add Demo" \
  -F "file=@./examples/ls-add-demo.csv;type=text/csv"
```

Expected shape:

```json
{
  "suite_id": "plc-suite-1",
  "title": "LS Add Demo",
  "imported_count": 3,
  "rejected_count": 0
}
```

## PLC Run Example

Queue a suite run:

```bash
curl -sS -X POST http://127.0.0.1:8000/plc-test-runs \
  -H "Content-Type: application/json" \
  -d '{"suite_id":"plc-suite-1","target_key":"stub-local"}'
```

Queue only one testcase:

```bash
curl -sS -X POST http://127.0.0.1:8000/plc-test-runs \
  -H "Content-Type: application/json" \
  -d '{"testcase_ids":["plc-suite-1::ADD_001"],"target_key":"stub-local"}'
```

Inspect run status:

```bash
curl -sS http://127.0.0.1:8000/plc-test-runs
curl -sS http://127.0.0.1:8000/plc-test-runs/<job_id>
curl -sS http://127.0.0.1:8000/plc-test-runs/<job_id>/items
curl -sS http://127.0.0.1:8000/plc-test-runs/<job_id>/items/<item_id>
```

Dashboard summary:

```bash
curl -sS http://127.0.0.1:8000/plc-dashboard/summary
```

## Reviewer UI

Open:

```text
http://127.0.0.1:8000/demo
```

The page now has two reviewer modes:

- **Workflow reviewer**: the original dataset/workflow/evidence experience
- **PLC testing MVP**: suite import, testcase preview, run queueing, run detail, raw I/O/result drill-down

## Stub Executor vs Future C++ Adapter

### Stub executor today

- deterministic
- pure JSON contract
- no live PLC I/O
- suitable for end-to-end validation of the queue, worker, API, and UI flow

### Future C++ adapter seam

- enabled through `PLC_EXECUTOR_MODE=cli`
- shells out through `api.services.plc.cli_adapter`
- expects one JSON object on stdout
- keeps the same request/response envelope as the stub executor

This is the compatibility point for reusing existing C++ PLC execution assets without rewriting the surrounding platform.

## LLM Assist Boundary

The current PLC platform does **not** let an LLM decide write/read sequences or final pass/fail. The LLM-related extension point is intentionally narrow:

- normalization suggestions
- row cleanup assistance
- description generation
- log summarization
- future natural-language search over test assets

The repo currently exposes a reviewable normalization preview endpoint:

```bash
curl -sS -X POST http://127.0.0.1:8000/plc-llm/suggest-testcase-normalization \
  -H "Content-Type: application/json" \
  -d '{
    "raw_row": {
      "instruction_name": "add",
      "input_values": "[[1,1]]",
      "expected_outputs": "[2]",
      "input_type": "LWORD",
      "output_type": "LWORD"
    }
  }'
```

In this MVP that path is still a deterministic preview seam, not a production LLM decision-maker.

## Testing

Install workspace dependencies:

```bash
uv sync --dev
```

Typecheck:

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

Targeted PLC verification:

```bash
uv run --project apps/api pytest -q \
  apps/api/tests/test_plc_api.py \
  apps/api/tests/test_plc_service.py \
  apps/api/tests/test_plc_runner.py

uv run --project apps/worker pytest -q \
  apps/worker/tests/test_job_processing.py \
  apps/worker/tests/test_plc_job_processing.py
```

## Current Limitations

- PLC suite storage is currently one table with normalized JSON, not a fully normalized relational case/result model
- no persistent PLC target registry yet
- no auth or multi-user review flow
- no browser-side spreadsheet mapping wizard
- no real C++ or live PLC binding in this repo yet
- `/demo` remains a static page, so richer charts/filters are intentionally modest

## Versioning and Milestones

The repo now explicitly starts milestone-based versioning:

- `v0.1.0`: original workflow reviewer skeleton
- `v0.2.0`: PLC suite import + queue-backed deterministic run MVP
- next likely milestone: `v0.3.0` for real C++ adapter integration, richer validators, and stronger reviewer drill-down

See `CHANGELOG.md` for the current milestone notes.
