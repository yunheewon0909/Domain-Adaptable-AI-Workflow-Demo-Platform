# Domain-Adaptable AI Workflow Demo Platform

## Overview

This repository is now positioned as an extensible monorepo-style skeleton for domain-adaptable AI and automation services. It still ships the original reviewer workflow demo, it includes a **DB-centered PLC test automation platform slice**, and it now also includes a **local AI ops slice** for fine-tuning dataset management, queue-backed training scaffolding, model registration, model-selectable inference, and separate RAG collection/document review.

The current milestone is best understood as **v0.6.0: a reviewer-first local AI ops expansion on top of the existing PLC and workflow skeleton**. The repo still does not include private C++ assets or live PLC bindings, and it still does not ship a heavy in-repo fine-tuning backend. What it now does provide is an end-to-end review flow for training data management, training job orchestration, artifact registration, model selection, and separate RAG data operations.

The key message of the repo is now threefold:

- **skeleton/demo**: a reviewer-friendly starter with FastAPI, worker, Postgres queue, and co-hosted static UI
- **domain service**: a concrete PLC testing slice that shows how Excel-based industrial test assets can be turned into a DB + queue + dashboard workflow without overhauling the skeleton
- **local AI ops**: a second concrete slice that shows how fine-tuning datasets, training jobs, model registry entries, model-selectable inference, and RAG collections can live beside the same queue and reviewer shell without collapsing into one mixed data model

## What the PLC Testing Slice Adds

The PLC slice focuses on this problem: LS PLC testcases often start life in spreadsheets, while actual write/read behavior already lives in existing execution assets such as C++ scripts. The current milestone turns those spreadsheet-defined cases into database-backed suite and testcase records, runs them through the existing worker queue, stores deterministic verdicts plus execution traces in a reviewable relational form, and makes the future native CLI integration contract much more explicit.

Included in the current milestone:

- CSV and XLSX suite import
- normalization of spreadsheet rows into runnable testcase records
- database-backed suite storage plus relational testcase master rows
- `plc_test_run` jobs on the existing `jobs` queue
- relational `plc_test_runs`, `plc_test_run_items`, and `plc_test_run_io_logs`
- deterministic stub PLC executor
- versioned CLI execution contract for future C++ subprocess integration
- exact-match validator with explicit failure reasons
- run/result APIs for suite-level, testcase-level, item-level, and raw I/O review
- target registry plus enqueue-time target validation via `/plc-targets`
- persisted reviewable PLC normalization suggestions
- dashboard summary API for recent runs, queue stats, and failure hotspots
- expanded `/demo` reviewer surface for PLC import, run, filter, suggestion review, and drill-down
- execution profile registry scaffolding linked from testcase masters
- persisted request/run snapshots on PLC runs and run items for reviewability
- normalized target metadata for environment/line/bench/tag review without storing secrets
- reviewer dashboard summaries for recent runs, target status, and instruction failure concentration
- suggestion payload schema versioning plus `suggestion_type` filtering for persisted review artifacts
- explicit `case_source` / `testcase_source` markers so definition-json fallback is visible instead of implicit

Out of scope for this milestone:

- real PLC hardware control
- authentication and permissions
- cancel/retry UI for PLC runs
- mutable suite versioning workflows
- live progress streaming beyond queue polling
- LLM-driven execution or pass/fail decisions

## What the AI Ops Slice Adds

The local AI ops slice focuses on reviewer-visible orchestration rather than pretending heavy training is already complete. In this milestone the important flow is:

1. register fine-tuning datasets and versioned rows
2. validate and lock a dataset version
3. enqueue a queue-backed training job scaffold
4. let the worker create a lightweight artifact manifest and model registry entry
5. pick a registered model during inference
6. manage RAG collections and documents separately from fine-tuning corpora

Included in the current milestone:

- `ft_datasets`, `ft_dataset_versions`, and `ft_dataset_rows` with row-level validation status
- dataset version status transitions (`draft -> validated -> locked`)
- `ft_train_model` queue jobs plus `ft_training_jobs` domain status tracking
- lightweight artifact manifests in `data/model_artifacts/` for training scaffold output
- `model_registry` entries for base models and fine-tuned placeholders
- `/models` and `/inference/run` so inference can choose a model source explicitly
- `rag_collections` and `rag_documents` tables for collection/document review
- txt/md/pdf upload support with parse preview or metadata preview
- retrieval preview over collection-managed document text previews
- new `/demo` reviewer modes for Fine-tuning, Models, and RAG

Current limitations of the AI ops slice:

- Ollama is still the serving target, not the trainer itself
- the training path is a lightweight scaffold that produces a reviewable artifact manifest and registry entry rather than a real adapter/merged model
- fine-tuned registry entries currently stay as reviewable placeholders and route inference back through the selected base serving model until a future import/publish seam is added
- RAG collection management is separate from the legacy dataset-backed retrieval flow and currently emphasizes metadata/text preview plus retrieval preview rather than full collection embedding lifecycle management

## Architecture Summary

### Runtime services

- `postgres`: queue and application metadata
- `api`: FastAPI app, routers, domain services, static demo UI, runner modules
- `worker`: Postgres-backed job worker that dispatches runner modules via subprocess
- `ollama`: local LLM/embedding runtime for the original reviewer workflows

### AI ops execution path

1. Create a fine-tuning dataset with `POST /ft-datasets`
2. Create a version with `POST /ft-datasets/{dataset_id}/versions`
3. Add rows with `POST /ft-dataset-versions/{version_id}/rows`
4. Mark the version `validated` and optionally `locked`
5. Enqueue `POST /ft-training-jobs`
6. Worker claims the backing `ft_train_model` job from `jobs`
7. Runner writes a lightweight artifact manifest and registers a model entry
8. `/models` and `/inference/run` expose the resulting model selection flow
9. `POST /rag-collections` plus collection document upload/retrieval preview stay separate from fine-tuning data management

### PLC execution path

1. Upload CSV/XLSX via `POST /plc-testcases/import`
2. Normalize rows into one stored PLC suite in `plc_test_suites` and testcase master rows in `plc_testcases`
3. Enqueue a `plc_test_run` job with `POST /plc-test-runs`
4. Materialize a matching `plc_test_runs` row and queued `plc_test_run_items`
5. Worker claims the queued job from the existing `jobs` table
6. Worker runs `api.services.plc.job_runner` via subprocess
7. Runner executes a deterministic stub executor or future CLI adapter, validates outputs, and persists run items plus raw I/O logs
8. Worker writes a compact compatibility summary back to `jobs.result_json`
9. Reviewer UI and PLC APIs read relational review data first, with suite JSON compatibility fallback used only when relational rows are missing

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

## PLC Relational Model

- `plc_test_suites`: import header and provenance snapshot (`definition_json` retained for provenance, compatibility fallback, and rollback)
- `plc_execution_profiles`: execution profile registry that keeps future adapter-facing metadata non-secret but explicit
- `plc_testcases`: relational testcase master rows expanded from spreadsheet input
- `plc_test_runs`: PLC domain run header linked 1:1 to the backing queue job
- `plc_test_run_items`: testcase-level execution and validation records
- `plc_test_run_io_logs`: ordered raw I/O snippets for run-item review
- `plc_targets`: target registry with built-in `stub-local` compatibility and executor-mode validation
- `plc_llm_suggestions`: persisted review artifacts for normalization proposals and future suggestion types

`jobs` remains the queue and lifecycle source of truth. The PLC run tables mirror that lifecycle so the PLC domain can be reviewed independently from the generic jobs table.

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
curl -sS http://127.0.0.1:8000/plc-test-runs/<job_id>/io-logs
curl -sS http://127.0.0.1:8000/plc-targets
```

Dashboard summary:

```bash
curl -sS http://127.0.0.1:8000/plc-dashboard/summary
curl -sS "http://127.0.0.1:8000/plc-dashboard/summary?suite_id=plc-suite-1"
curl -sS "http://127.0.0.1:8000/plc-test-runs?suite_id=plc-suite-1&target_key=stub-local&status=succeeded&failed_only=true"
```

## Reviewer UI

Open:

```text
http://127.0.0.1:8000/demo
```

The page now has five reviewer modes:

- **Workflow reviewer**: the original dataset/workflow/evidence experience
- **PLC testing MVP**: suite import, testcase preview, queued/running/succeeded/failed run review, and raw I/O/result drill-down
- **Fine-tuning**: dataset creation, version management, row review, validation status transitions, and training enqueue controls
- **Models**: model registry inspection plus model-selectable inference with optional RAG collection context
- **RAG**: collection creation, document upload/list/detail, and retrieval preview

## AI Ops API Examples

Create a fine-tuning dataset:

```bash
curl -sS -X POST http://127.0.0.1:8000/ft-datasets \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Instruction tuning demo",
    "task_type": "instruction_sft",
    "schema_type": "json",
    "description": "Reviewer-visible local tuning dataset"
  }'
```

Create a dataset version and add rows:

```bash
curl -sS -X POST http://127.0.0.1:8000/ft-datasets/ft-dataset-1/versions \
  -H "Content-Type: application/json" \
  -d '{"version_label":"v1","train_split_ratio":0.8,"val_split_ratio":0.1,"test_split_ratio":0.1}'

curl -sS -X POST http://127.0.0.1:8000/ft-dataset-versions/ft-version-1/rows \
  -H "Content-Type: application/json" \
  -d '{
    "rows": [
      {
        "split": "train",
        "input_json": {"instruction": "summarize", "input": "shift handover note"},
        "target_json": {"output": "short summary"},
        "metadata_json": {"source": "manual-demo"}
      }
    ]
  }'

curl -sS -X POST http://127.0.0.1:8000/ft-dataset-versions/ft-version-1/status \
  -H "Content-Type: application/json" \
  -d '{"status":"validated"}'
```

Enqueue a training scaffold job:

```bash
curl -sS -X POST http://127.0.0.1:8000/ft-training-jobs \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_version_id": "ft-version-1",
    "base_model_name": "qwen2.5:7b-instruct-q4_K_M",
    "training_method": "stub_adapter",
    "hyperparams_json": {"epochs": 1}
  }'
```

Inspect registered models and run inference:

```bash
curl -sS http://127.0.0.1:8000/models

curl -sS -X POST http://127.0.0.1:8000/inference/run \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Summarize the latest maintenance note",
    "model_id": "model-1"
  }'
```

Create a RAG collection, upload a document, and preview retrieval:

```bash
curl -sS -X POST http://127.0.0.1:8000/rag-collections \
  -H "Content-Type: application/json" \
  -d '{"name":"Maintenance docs","description":"Grounding material for local reviewer runs"}'

curl -sS -X POST http://127.0.0.1:8000/rag-collections/rag-collection-1/documents \
  -F "file=@./README.md;type=text/markdown"

curl -sS -X POST http://127.0.0.1:8000/rag-retrieval/preview \
  -H "Content-Type: application/json" \
  -d '{"collection_id":"rag-collection-1","query":"maintenance automation","top_k":3}'
```

## Stub Executor vs Future C++ Adapter

### Stub executor today

- deterministic
- pure JSON contract
- no live PLC I/O
- suitable for end-to-end validation of the queue, worker, API, and UI flow

### Future C++ adapter seam

- enabled through `PLC_EXECUTOR_MODE=cli`
- shells out through `api.services.plc.cli_adapter`
- uses versioned request/response envelopes shared with the deterministic stub executor
- rejects empty stdout, invalid JSON, schema-invalid payloads, non-zero exits, and timeouts as infrastructure failures
- keeps validator-owned pass/fail outside the native executor boundary

Current request envelope fields:

- `schema_version`
- `testcase_id`
- `instruction`
- `input_type`
- `output_type`
- `inputs`
- `expected`
- `expected_outcome`
- `memory_profile_key`
- `execution_profile_key`
- `execution_profile`
- `timeout_ms`
- `target_key`
- `testcase_context`
- `run_context`
- `target_context`
- `extension_json`

Current result envelope fields:

- `schema_version`
- `status`
- `write_values`
- `read_values`
- `actual_output`
- `expected_output`
- `duration_ms`
- `raw_log`
- `executor_exit_code`
- `diagnostics`
- `warning_codes`
- `executor_metadata`

This is the compatibility point for reusing existing C++ PLC execution assets without rewriting the surrounding platform.

### Execution metadata and memory profile preparation

The repo still does **not** contain private PLC addresses, commands, or native execution scripts. Instead, it now exposes the structure those contracts will eventually attach to:

- testcase masters retain `memory_profile_key`
- testcase masters link to `plc_execution_profiles`
- execution profiles make `instruction_name`, `input_type`, `output_type`, timeout policy, setup/reset placeholders, notes, and future address-contract placeholders explicit
- queued PLC runs snapshot the normalized target metadata and request schema version
- run items persist enough request context to explain what was executed without making the fallback JSON or the LLM layer the source of truth

That means the repo is now prepared for future adapter binding work while still staying fully deterministic and non-secret today.

### Target registry rules

- `/plc-targets` always exposes a runnable `stub-local` target for the deterministic in-repo executor
- `POST /plc-test-runs` now validates that the requested target exists, is active, and matches the configured executor mode before queue rows are created
- target metadata is normalized into a review-friendly shape (`environment_label`, `line`, `bench`, `tags`, extra non-secret attributes)
- target metadata remains non-secret and mock-friendly in this repo; credentials and live PLC connection details are still out of scope

## LLM Assist Boundary

The current PLC platform does **not** let an LLM decide write/read sequences or final pass/fail. The LLM-related extension point is intentionally narrow:

- normalization suggestions
- row cleanup assistance
- description generation
- log summarization
- future natural-language search over test assets

The repo now exposes both a reviewable normalization preview and a persisted review flow:

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

Persist a suggestion during preview generation:

```bash
curl -sS -X POST http://127.0.0.1:8000/plc-llm/suggest-testcase-normalization \
  -H "Content-Type: application/json" \
  -d '{
    "suite_id": "plc-suite-1",
    "testcase_id": "plc-suite-1::ADD_001",
    "persist": true,
    "raw_row": {
      "instruction_name": "add",
      "input_values": "[[1,1]]",
      "expected_outputs": "[2]",
      "input_type": "LWORD",
      "output_type": "LWORD"
    }
  }'
```

Review persisted suggestions:

```bash
curl -sS http://127.0.0.1:8000/plc-llm/suggestions
curl -sS "http://127.0.0.1:8000/plc-llm/suggestions?suite_id=plc-suite-1&status=pending&suggestion_type=normalization"
curl -sS http://127.0.0.1:8000/plc-llm/suggestions/<id>
curl -sS -X POST http://127.0.0.1:8000/plc-llm/suggestions/<id>/review \
  -H "Content-Type: application/json" \
  -d '{"status":"accepted"}'
```

This remains a reviewable artifact flow, not a production LLM decision-maker and not an automatic testcase mutation path.

Persisted suggestions now also carry a payload schema version, keep canonical `suggestion_type` values, and support list filtering by `suite_id`, `testcase_id`, `status`, and `suggestion_type`.

Review flow is intentionally narrow:

- `pending -> accepted`
- `pending -> rejected`
- once a suggestion leaves `pending`, it remains a review artifact and is not auto-applied to testcase masters

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

Targeted AI ops verification:

```bash
uv run --project apps/api pytest -q \
  apps/api/tests/test_ai_ops_api.py \
  apps/api/tests/test_demo_ui.py

uv run --project apps/worker pytest -q \
  apps/worker/tests/test_job_processing.py
```

## Reviewer UI

The co-hosted `/demo` surface still stays inside the existing static shell, but it now spans both PLC review and local AI ops review:

- suite-scoped or all-suite dashboard refresh
- target status and instruction failure profile panels
- testcase filters for instruction, input type, expected outcome, and saved suggestion state
- target-aware run filters with failed/problem-only drill-down
- richer run detail panels with target context, request payloads, validator payloads, executor logs, and sequence-oriented I/O timelines
- fine-tuning dataset, version, row, and training job panels
- model registry inspection and model-selectable inference runs
- RAG collection/document management and retrieval preview

The original workflow reviewer mode is still preserved, and the new AI ops modes stay in the same shell rather than branching into a separate frontend.

## Current Limitations

- suite provenance still remains duplicated in `plc_test_suites.definition_json`, but relational testcase rows now drive normal list and run selection flows; fallback now stays explicit through `case_source` / `testcase_source`, and partial relational drift is treated as an error during run enqueue instead of silently falling back
- target registry is still intentionally lightweight, even though queue-time validation now enforces active and executor-compatible targets
- no auth or multi-user review flow
- no browser-side spreadsheet mapping wizard
- no real C++ or live PLC binding in this repo yet
- persisted LLM suggestions remain review-only and are not auto-applied to testcase masters
- `/demo` remains a static page, so richer charts/filters are still intentionally modest compared with a dedicated frontend
- fine-tuning still uses a lightweight training scaffold rather than a real trainer backend
- fine-tuned registry entries are reviewable placeholders and not yet published/imported as standalone Ollama artifacts
- RAG collection previews use extracted text and retrieval preview, not a full per-collection embedding/index lifecycle yet

## Versioning and Milestones

The repo now explicitly uses milestone-based versioning:

- `v0.1.0`: original workflow reviewer skeleton
- `v0.2.0`: PLC suite import + queue-backed deterministic run MVP
- `v0.3.0`: relational PLC testcase/run persistence + stronger reviewer drill-down
- `v0.4.0`: versioned CLI contract, active target validation, relational-first suite review boundaries, persisted suggestion review flow, and richer PLC reviewer filters/drill-down
- `v0.5.0`: execution profile scaffolding, normalized target metadata, reviewer/dashboard hardening, typed suggestion review artifacts, and explicit fallback markers before native adapter work
- `v0.6.0`: fine-tuning dataset management, queue-backed training scaffolding, model registry plus model-selectable inference, separate RAG collection management, and expanded reviewer modes
- next likely milestone: `v0.6.x` for hardening or `v0.7.0` once real trainer/publish flows and broader operational controls land

See `CHANGELOG.md` for the current milestone notes.
