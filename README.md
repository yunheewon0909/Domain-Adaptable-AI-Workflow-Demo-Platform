# Domain-Adaptable AI Workflow Demo Platform

## Overview

This repository is now positioned as an extensible monorepo-style skeleton for domain-adaptable AI and automation services. It still ships the original reviewer workflow demo, it includes a **DB-centered PLC test automation platform slice**, and it now also includes a **local AI ops slice** for fine-tuning dataset management, queue-backed real training jobs, model registry review, separate inference selection, separate workflow source selection, and separate RAG collection/document review. The Models cards now expose explicit Review details and Use for inference actions, and the in-panel inference summary is clearer.

The current milestone is best understood as **v0.7.7: runtime E2E hardening for the real local SFT + LoRA, workflow, RAG, and PLC demo paths**. The repo still does not include private C++ assets or live PLC bindings, and it still does not claim a full production fine-tuning platform. What it now provides is an end-to-end review flow for training data management, queue-backed real training execution, artifact registration, smoke-test validation, truthful model readiness, guided Fine-tuning smoke-job progress tracking inside `/demo`, runtime-aware preflight guidance in the same reviewer surface, clearer fine-tuning troubleshooting messages, graceful workflow guidance when the legacy RAG index is not initialized, collection-managed workflow source review, separate RAG data operations with document deletion, and executable Docker/API/worker/Ollama E2E scripts, while keeping artifact-only rows reviewable and not inference-selectable.

The key message of the repo is now threefold:

- **skeleton/demo**: a reviewer-friendly starter with FastAPI, worker, Postgres queue, and co-hosted static UI
- **domain service**: a concrete PLC testing slice that shows how Excel-based industrial test assets can be turned into a DB + queue + dashboard workflow without overhauling the skeleton
- **local AI ops**: a second concrete slice that shows how fine-tuning datasets, training jobs, real adapter artifacts, model registry entries, publish-ready serving seams, separate review versus inference selection in the Models tab, clearer in-panel inference summaries, workflow source selection, and RAG collections can live beside the same queue and reviewer shell without collapsing into one mixed data model

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

The local AI ops slice focuses on reviewer-visible orchestration with a narrow but real local training path. In this milestone the important flow is:

1. register fine-tuning datasets and versioned rows
2. validate and lock a dataset version
3. lock a dataset version into an immutable training snapshot
4. enqueue a queue-backed `sft_lora` training job
5. let the worker export trainer-ready JSONL, run a local PEFT/Transformers LoRA path, and persist real artifacts
6. register the resulting model as `artifact_ready` after adapter/report/manifest validation succeeds
7. keep the model artifact-only until a real serving/import step exists; the current publish seam prepares metadata but does not create an Ollama runtime model
8. manage RAG collections and documents separately from fine-tuning corpora

Included in the current milestone:

- `ft_datasets`, `ft_dataset_versions`, and `ft_dataset_rows` with row-level validation status
- dataset version status transitions (`draft -> validated -> locked`)
- `ft_train_model` queue jobs plus richer `ft_training_jobs` domain status tracking (`queued -> preparing_data -> training -> packaging -> registering -> succeeded/failed`)
- real dataset export, adapter bundle, training report, and publish-manifest artifacts under `data/model_artifacts/`
- `model_registry` entries for base models and fine-tuned artifact-ready or published models
- `/models` and `/inference/run` so the Models tab can show explicit Review details, a separate Use for inference action, and a clearer in-panel inference summary while keeping artifact-only rows out of inference selection
- `/ft-training-jobs/{job_id}/publish`, `/ft-model-artifacts/{artifact_id}`, `/ft-dataset-versions/{version_id}/summary`, `/models/{model_id}/lineage`, and `/ft-training-jobs/{job_id}/logs`
- `rag_collections` and `rag_documents` tables for collection/document review
- txt/md/pdf upload support with parse preview or metadata preview
- retrieval preview over collection-managed document text previews
- new `/demo` reviewer modes for Fine-tuning, Models, and RAG
- Fine-tuning mode can prepare a smoke dataset, version, rows, validation, and lock flow using the existing endpoints already documented in this repo, with no hidden import wizard
- workflow source selection stays separate from model inference selection, so choosing a workflow RAG source does not change the model selector in Models

Current limitations of the AI ops slice:

- Ollama is still the serving target, not the trainer itself
- the built-in trainer path is intentionally narrow: one supervised `sft_lora` route, one local backend, and explicit local environment guards
- training can produce real adapter artifacts when the local environment supports it, but the default success target is still an artifact-valid smoke test, not an Ollama-serving success case
- the current publish step is a truthful seam, not a claim of direct fine-tuning inside Ollama; automatic end-to-end Ollama packaging/import is not implemented in this repo
- RAG collection management is separate from the legacy dataset-backed retrieval flow and currently emphasizes metadata/text preview plus retrieval preview rather than full collection embedding lifecycle management

## What actually happens during fine-tuning

For the current local SFT + LoRA path, a successful training job means:

1. the selected dataset version is exported into trainer-ready JSONL
2. the local PEFT/Transformers backend runs LoRA training against the resolved trainer model
3. a PEFT adapter artifact is written under `data/model_artifacts/<job_id>/trainer_output/adapter/`
4. a `training_report.json` plus `training.log` are written beside it
5. a reviewer-facing `publish_manifest.json` and `Modelfile.template` are generated
6. a `model_registry` row is created with `status=artifact_ready` and `publish_status=publish_ready`

The important distinction is that this output is a **validated adapter artifact package**, not a finished Ollama runtime model. The deterministic fallback path validates the artifact pipeline, not model quality.

## What does not happen yet

- no automatic real `ollama create` or `ollama import`
- no direct fine-tuning inside Ollama
- no guarantee that large-model training is realistic on a MacBook Air-class machine
- no automatic conversion from PEFT adapter output into GGUF or another Ollama-ready merged format

## Model naming and lineage

The current AI ops flow intentionally keeps several names distinct:

- `base_model_name`: the serving/base lineage the reviewer selected in the UI or API
- `trainer_model_name`: the actual Hugging Face trainer checkpoint used by the local PEFT backend
- `display_name`: the reviewer-facing registry label for the resulting artifact entry
- `artifact::<training_job_id>`: the internal placeholder serving key for an artifact-only fine-tuned registry row
- `candidate_published_model_name`: the namespace/job-based serving name the repo would use if a real import step existed

For smoke tests, `base_model_name` and `trainer_model_name` may differ on purpose. That does **not** mean the serving model itself was fine-tuned.

## MacBook / Apple Silicon smoke test

Use the current smoke-test path to verify that the pipeline works locally without pretending that a large production model was trained.

Recommended environment:

- `TRAINING_DEVICE=mps` on Apple Silicon when MPS is available
- keep `TRAINING_ALLOW_CPU=false` by default
- only enable `TRAINING_ALLOW_CPU=true` for a tiny fallback smoke run
- map a serving lineage to a tiny trainer model through `FT_TRAINER_MODEL_MAP_JSON`

Important runtime boundary:

- the **worker runtime** is where the training subprocess actually runs, so that is the environment that must satisfy `torch`, `transformers`, `peft`, `datasets`, `accelerate`, artifact-directory permissions, and device checks
- a **Docker-hosted API** can still work with a **host-run worker**; in that mixed setup, the host worker is the place where Apple Silicon `mps` validation matters
- a standard **Docker Linux worker** should be treated as a non-MPS path even on an Apple Silicon Mac

Included helper assets:

- sample dataset: `examples/ft_smoke_instruction_dataset.jsonl`
- helper script: `scripts/ft_smoke_test.sh`
- preflight checker: `scripts/ft_smoke_preflight.sh` (runs through the target worker runtime: host `uv --project apps/api` for host checks, worker-container execution for `--worker-runtime docker`)
- `/demo` smoke guide: now surfaces the same host-vs-docker preflight commands plus short runtime-boundary warnings before the reviewer queues a smoke job

Smoke hyperparameter preset:

```json
{
  "trainer_model_name": "hf-internal/testing-tiny-random-gpt2",
  "epochs": 1,
  "batch_size": 1,
  "gradient_accumulation_steps": 1,
  "learning_rate": 0.0005,
  "max_seq_length": 256,
  "lora_r": 4,
  "lora_alpha": 8,
  "lora_dropout": 0.0,
  "seed": 42,
  "smoke_test": true
}
```

Rough expectations for a local smoke test:

- runtime should be treated as a short pipeline verification, not a benchmark or realistic large-model training claim
- success means `ft_training_jobs.status == succeeded`
- `data/model_artifacts/<job_id>/trainer_output/adapter/` exists
- `training_report.json` exists
- `/models` shows a fine-tuned row with `artifact_ready` / `publish_ready`
- artifact-only rows stay reviewable, but inference remains blocked until a serving-ready selectable model exists

## Fine-tuning smoke runtime validation paths

### 1. Docker stack validation

Use this path to confirm that the queue-backed API/worker wiring is alive:

```bash
docker compose up -d postgres api worker
./scripts/ft_smoke_preflight.sh --worker-runtime docker
```

This validates the Docker stack shape, and the Compose defaults now make that Docker path CPU-friendly for tiny smoke tests. It is a deterministic artifact-pipeline check, not a model quality check, and it does **not** turn a Docker Linux worker into an Apple Silicon MPS runtime.
The preflight command above executes inside the worker container so dependency and device checks reflect the Docker worker runtime instead of the caller shell.
`API_BASE_URL` defaults to `http://api:8000` for this Docker path unless you override it explicitly.

### 2. Mixed Docker API + host worker validation

Use this path for Apple Silicon smoke runs where the API is reachable through Docker but the training subprocess needs to run on the host. This is the path that exercises real host-worker MPS readiness:

```bash
docker compose up -d postgres api

export WORKER_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai
export WORKER_ID=worker-local
export WORKER_HEARTBEAT_SECONDS=30
export WORKER_POLL_SECONDS=5
export JOB_MAX_ATTEMPTS=3
export WORKER_API_PROJECT_DIR="$(pwd)/apps/api"
export TRAINING_DEVICE=mps
export TRAINING_ALLOW_CPU=false
export MODEL_ARTIFACT_DIR="$(pwd)/data/model_artifacts"
export FT_DEFAULT_TRAINING_METHOD=sft_lora
export FT_TRAINER_BACKEND=local_peft
export FT_MAX_SEQ_LENGTH=1024
export FT_TRAINER_MODEL_MAP_JSON='{"qwen2.5:7b-instruct-q4_K_M":"hf-internal/testing-tiny-random-gpt2"}'
export OLLAMA_PUBLISH_ENABLED=false
export OLLAMA_MODEL_NAMESPACE=demo

./scripts/ft_smoke_preflight.sh --worker-runtime host
uv run --project apps/worker python -m worker.main
```

Once the preflight is clean and the worker is running, enqueue the smoke flow with:

```bash
./scripts/ft_smoke_test.sh
```

### 3. Full host-run validation

Use the existing host-only API and worker instructions below when you want both services to run outside Docker. Run the preflight before enqueueing the smoke job:

```bash
./scripts/ft_smoke_preflight.sh --worker-runtime host
```

For the host path, `API_BASE_URL` defaults to `http://127.0.0.1:8000` unless you override it explicitly.

## Fine-tuning smoke troubleshooting

- `GET /health` fails: the API is not reachable yet, so smoke enqueueing will fail before any worker/device logic matters
- `TRAINING_DEVICE=mps` fails in preflight: MPS must be validated from a host worker runtime, and `torch.backends.mps.is_available()` must be true in that host Python
- Docker preflight disagrees with your host shell: trust the runtime that will actually execute the worker subprocess; `--worker-runtime docker` inspects the worker container, while the default host path uses `uv --project apps/api`
- dependency import failures: install the training stack in the runtime that will execute the worker subprocess, not just in the shell where you happen to run curl
- artifact directory write failures: fix `MODEL_ARTIFACT_DIR` before enqueueing, because the smoke flow writes dataset exports, adapter artifacts, reports, logs, and publish manifests there
- tiny model download failures: the first run may need network access to resolve `hf-internal/testing-tiny-random-gpt2` if it is not already cached
- `/demo` training failure cards now split the user-facing summary, technical phase, next-step remediation, and raw technical detail so the reviewer can distinguish CPU fallback policy, Docker MPS mismatch, dependency/import issues, trainer-model download failures, dataset locking problems, and artifact validation failures without reading raw logs first

### Smoke-test guide in `/demo`

The Fine-tuning page can now stage the smoke dataset, create the version, add rows, move the version through validated and locked, enqueue the smoke job with preset defaults, auto-select and poll the active training job through its backend phases, and hand the resulting artifact over to Models through a review-only CTA. The same panel now also surfaces runtime-preflight commands and short boundary warnings so the reviewer sees host-worker Apple Silicon MPS guidance, Docker worker non-MPS guidance, and CPU fallback opt-in copy before enqueueing. That keeps the demo flow truthful, because it uses the same existing endpoints documented below instead of a fake import path or a separate backend shortcut.

The preflight helper itself now has deterministic unit-test coverage for API health failures, missing Python dependencies, MPS topology and availability checks, CPU fallback policy, auto-device resolution, artifact-directory writability, and empty trainer-model-map warnings.

## When can inference use a fine-tuned model?

Only when a **real serving model exists** and the registry entry is genuinely serving-ready. In the current repo, artifact-only rows stay reviewable in the detail panel, but only serving-ready selectable rows can be used for inference. The Models card keeps that split visible with explicit Review details and Use for inference actions, and only runtime-ready selectable models appear in the workflow/model inference selectors.

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
7. Runner exports a trainer-ready dataset snapshot, trains an adapter, writes a training report, and creates a publish-ready manifest
8. Registry rows stay `artifact_ready` until a serving seam marks them `published`
9. `/models` and `/inference/run` expose separate review and inference selection flows with readiness gating
10. `POST /rag-collections` plus collection document upload/retrieval preview stay separate from fine-tuning data management

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

4. Wait for the API container to finish its startup migration.

```bash
docker compose logs api --tail 50
```

5. Optional but recommended: initialize the legacy workflow RAG index if you want the legacy workflow source.

The workflow reviewer can use the legacy dataset-backed `data/rag_index/rag.db` source or collection-managed RAG sources from the RAG tab. `/demo` now fails gracefully when the legacy index is missing, but legacy retrieval-backed workflow evidence will stay unavailable until you initialize it.
That source choice stays separate from the Models inference selector, so changing workflow sources does not change model readiness or selection.

```bash
docker compose exec -T api uv run rag-ingest
# or the one-shot helper service
docker compose run --rm rag_ingest
```

6. Check the core routes.

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/workflows
curl -s http://127.0.0.1:8000/plc-dashboard/summary
curl -s http://127.0.0.1:8000/demo
```

## Docker-first demo readiness notes

- **Workflow reviewer source choice**: Workflow mode can use the legacy dataset-backed `rag.db` source or collection-managed RAG sources. If the legacy index is missing, `/demo` shows `RAG index is not ready`, explains that you should run `rag-ingest` or enqueue a RAG reindex, and keeps the job result readable instead of surfacing a noisy subprocess failure.
- **RAG collection-managed documents are different**: the RAG tab manages `rag_collections` / `rag_documents` metadata, text previews, retrieval preview, and document deletion. Those collection-managed documents are separate from the legacy workflow `rag.db` index, and they stay preview-based rather than a full embedding lifecycle.
- **Docker CPU smoke profile**: `compose.yml` now pins the API and worker demo path to CPU-friendly smoke defaults (`TRAINING_DEVICE=cpu`, `TRAINING_ALLOW_CPU=true`, `FT_MAX_SEQ_LENGTH=256`, artifact-only publish seam off) so Mac/Windows Docker Compose runs can validate tiny smoke jobs without pretending a large-model CPU training path is practical.
- **Host Apple Silicon MPS profile**: use the host-worker path when you want actual MPS validation. Docker Linux workers should still be treated as non-MPS runtimes even on Apple Silicon hosts.

## Host-Only Run

API:

```bash
export API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai
export OLLAMA_TIMEOUT_SECONDS=120
export PLC_EXECUTOR_MODE=stub
export TRAINING_DEVICE=auto
export TRAINING_ALLOW_CPU=false
export MODEL_ARTIFACT_DIR="$(pwd)/data/model_artifacts"
export FT_DEFAULT_TRAINING_METHOD=sft_lora
export FT_TRAINER_BACKEND=local_peft
export FT_MAX_SEQ_LENGTH=1024
export FT_TRAINER_MODEL_MAP_JSON='{"qwen2.5:7b-instruct-q4_K_M":"hf-internal/testing-tiny-random-gpt2"}'
export OLLAMA_PUBLISH_ENABLED=false
export OLLAMA_MODEL_NAMESPACE=demo

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
export TRAINING_DEVICE=auto
export TRAINING_ALLOW_CPU=false
export MODEL_ARTIFACT_DIR="$(pwd)/data/model_artifacts"
export FT_DEFAULT_TRAINING_METHOD=sft_lora
export FT_TRAINER_BACKEND=local_peft
export FT_MAX_SEQ_LENGTH=1024
export FT_TRAINER_MODEL_MAP_JSON='{"qwen2.5:7b-instruct-q4_K_M":"hf-internal/testing-tiny-random-gpt2"}'
export OLLAMA_PUBLISH_ENABLED=false
export OLLAMA_MODEL_NAMESPACE=demo

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
- **Models**: model registry inspection plus separate inference selection with optional RAG collection context, with explicit Review details and Use for inference actions on each card
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

curl -sS -X POST http://127.0.0.1:8000/ft-dataset-versions/ft-version-1/status \
  -H "Content-Type: application/json" \
  -d '{"status":"locked"}'
```

Enqueue a real local SFT + LoRA job:

```bash
curl -sS -X POST http://127.0.0.1:8000/ft-training-jobs \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_version_id": "ft-version-1",
    "base_model_name": "qwen2.5:7b-instruct-q4_K_M",
    "training_method": "sft_lora",
    "hyperparams_json": {
      "epochs": 1,
      "learning_rate": 0.0002,
      "batch_size": 1,
      "gradient_accumulation_steps": 1,
      "max_seq_length": 512,
      "lora_r": 8,
      "lora_alpha": 16,
      "lora_dropout": 0.05,
      "trainer_model_name": "hf-internal/testing-tiny-random-gpt2"
    }
  }'
```

Inspect jobs, artifacts, logs, and model readiness:

```bash
curl -sS http://127.0.0.1:8000/ft-training-jobs
curl -sS http://127.0.0.1:8000/ft-training-jobs/ft-job-1
curl -sS http://127.0.0.1:8000/ft-training-jobs/ft-job-1/logs
curl -sS http://127.0.0.1:8000/ft-dataset-versions/ft-version-1/summary
curl -sS http://127.0.0.1:8000/models
curl -sS http://127.0.0.1:8000/models/model-1/lineage
curl -sS http://127.0.0.1:8000/ft-model-artifacts/artifact-1

curl -sS -X POST http://127.0.0.1:8000/ft-training-jobs/ft-job-1/publish
```

Run inference only with a serving-ready model:

```bash

curl -sS -X POST http://127.0.0.1:8000/inference/run \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Summarize the latest maintenance note",
    "model_id": "model-1"
  }'
```

Create a RAG collection, upload a document, preview retrieval, and delete a document:

```bash
curl -sS -X POST http://127.0.0.1:8000/rag-collections \
  -H "Content-Type: application/json" \
  -d '{"name":"Maintenance docs","description":"Grounding material for local reviewer runs"}'

curl -sS -X POST http://127.0.0.1:8000/rag-collections/rag-collection-1/documents \
  -F "file=@./README.md;type=text/markdown"

curl -sS -X POST http://127.0.0.1:8000/rag-retrieval/preview \
  -H "Content-Type: application/json" \
  -d '{"collection_id":"rag-collection-1","query":"maintenance automation","top_k":3}'

curl -sS -X DELETE http://127.0.0.1:8000/rag-documents/rag-doc-1
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
  apps/api/tests/test_ft_dataset_export.py \
  apps/api/tests/test_ft_training_runner.py \
  apps/api/tests/test_demo_ui.py

uv run --project apps/worker pytest -q \
  apps/worker/tests/test_job_processing.py
```

Training environment defaults are documented in `.env.example`. The most important variables are:

- `TRAINING_DEVICE`: prefer `mps` on Apple Silicon; other options are `auto`, `cuda`, or `cpu`
- `TRAINING_ALLOW_CPU`: keep `false` unless you are intentionally running a tiny smoke-test model on CPU
- `MODEL_ARTIFACT_DIR`: local root for exported datasets, adapters, reports, and publish manifests
- `FT_TRAINER_MODEL_MAP_JSON`: maps serving lineage names to actual trainer model identifiers
- `OLLAMA_PUBLISH_ENABLED` and `OLLAMA_MODEL_NAMESPACE`: control the publish/import seam without claiming in-place Ollama fine-tuning

Quick local smoke-test sequence:

```bash
./scripts/ft_smoke_preflight.sh
./scripts/ft_smoke_test.sh
curl -sS http://127.0.0.1:8000/ft-training-jobs/<job_id>
curl -sS http://127.0.0.1:8000/models
```

## Runtime E2E validation

The `pytest` suites in `apps/api/tests` and `apps/worker/tests` are still the fast contract layer. They intentionally do **not** replace live runtime validation of Docker, worker subprocesses, queue polling, real Ollama-backed inference, collection-managed workflow evidence, or artifact-only model gating.

For that live path, use the `scripts/e2e_*` entrypoints.

### What these E2E scripts validate

- Docker stack startup and core route availability
- real `/inference/run` requests against a runtime-ready/selectable model
- workflow job enqueueing plus `/jobs/{job_id}` polling with explicit `model_id`
- collection-managed RAG documents used as workflow evidence
- queue-backed fine-tuning smoke jobs and artifact-path validation
- artifact-only model rejection for inference and workflow selection
- RAG document CRUD plus retrieval-preview refresh
- PLC CSV import plus stub-local run polling and result review

### Prerequisites

Docker/full-stack validation:

```bash
docker volume create ollama-models || true
docker compose up -d --build
```

If Ollama is running but the serving models are missing, pull them into the running runtime:

```bash
docker compose exec -T ollama ollama pull qwen2.5:3b-instruct-q4_K_M
docker compose exec -T ollama ollama pull qwen2.5:7b-instruct-q4_K_M
docker compose exec -T ollama ollama pull nomic-embed-text
```

### Selectable-model policy

Inference-dependent E2E scripts expect `/models` to expose at least one `readiness.selectable == true` row.

- default behavior: fail if no selectable model exists
- optional skip behavior: `E2E_ALLOW_NO_MODEL_SKIP=true`

This is deliberate. Artifact-only `artifact_ready` / `publish_ready` rows are reviewable, but they are **not** runtime-ready serving models.

### Recommended execution order

```bash
./scripts/e2e_docker_stack_smoke.sh
python scripts/e2e_ollama_inference_smoke.py
python scripts/e2e_workflow_real_model_smoke.py
python scripts/e2e_rag_collection_workflow_smoke.py
python scripts/e2e_ft_smoke_fallback.py
python scripts/e2e_model_gating_smoke.py
python scripts/e2e_rag_document_management.py
python scripts/e2e_plc_stub_pipeline.py
python scripts/e2e_job_queue_processing.py
```

Or run the main bundle:

```bash
./scripts/e2e_run_all.sh
```

### Skip / fail behavior

- no selectable model: fail by default, optional skip with `E2E_ALLOW_NO_MODEL_SKIP=true`
- missing legacy `rag.db`: workflow E2E treats a structured `RAG index is not ready` result as success, because the goal is graceful degradation instead of subprocess failure
- artifact-only fine-tuned model: must stay blocked from inference/workflow selection
- FT smoke path: validates artifact/report/registry behavior and truthful readiness, not model quality or automatic Ollama import

### Browser E2E status

This repository does not currently include a configured Playwright toolchain. A deferred skeleton lives at `tests/e2e/playwright/demo_happy_path.spec.ts` so the intended browser happy path is recorded without pretending that a passing browser suite already exists.

For the fuller runbook and troubleshooting notes, see `docs/runtime-validation.md`.

## Reviewer UI

The co-hosted `/demo` surface still stays inside the existing static shell, but it now spans both PLC review and local AI ops review:

- suite-scoped or all-suite dashboard refresh
- target status and instruction failure profile panels
- testcase filters for instruction, input type, expected outcome, and saved suggestion state
- target-aware run filters with failed/problem-only drill-down
- richer run detail panels with target context, request payloads, validator payloads, executor logs, and sequence-oriented I/O timelines
- fine-tuning dataset, version, row, and training job panels
- model registry inspection and separate inference selection runs
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
- the repo now supports one real local `sft_lora` path, but it still expects a compatible local Python training stack and does not pretend all environments can train large models
- fine-tuned registry entries are no longer silently routed through the base model; they stay `artifact_ready` with a validated adapter/report/manifest package until a real serving model exists
- the publish seam is still intentionally modest and reviewer-oriented; it prepares metadata for a future serving step rather than claiming a full automatic Ollama packaging pipeline
- RAG collection previews use extracted text and retrieval preview, not a full per-collection embedding/index lifecycle yet

## Versioning and Milestones

The repo now explicitly uses milestone-based versioning:

- `v0.1.0`: original workflow reviewer skeleton
- `v0.2.0`: PLC suite import + queue-backed deterministic run MVP
- `v0.3.0`: relational PLC testcase/run persistence + stronger reviewer drill-down
- `v0.4.0`: versioned CLI contract, active target validation, relational-first suite review boundaries, persisted suggestion review flow, and richer PLC reviewer filters/drill-down
- `v0.5.0`: execution profile scaffolding, normalized target metadata, reviewer/dashboard hardening, typed suggestion review artifacts, and explicit fallback markers before native adapter work
- `v0.6.0`: fine-tuning dataset management, queue-backed training scaffolding, model registry plus model-selectable inference, separate RAG collection management, and expanded reviewer modes
- `v0.7.0`: real local SFT + LoRA runner, dataset export formatting, artifact-ready vs published model readiness, publish-ready serving seam, richer FT/model APIs, and reviewer/UI hardening
- `v0.7.1`: smoke-test hardening, trainer/serving lineage clarity, adapter artifact validation, and more explicit readiness documentation
- `v0.7.2`: guided smoke training in `/demo`, FT lifecycle polling, clearer artifact/error emphasis, and review-only Models handoff after successful fine-tuning smoke runs
- `v0.7.3`: topology-aware smoke preflight checks, host-worker Apple Silicon MPS guidance, and clearer Docker-versus-host troubleshooting for local fine-tuning validation
- `v0.7.4`: `/demo` runtime preflight guidance, stronger smoke-runtime boundary copy, and deterministic preflight unit-test coverage
- `v0.7.5`: graceful workflow RAG-index readiness guidance, Docker CPU-smoke defaults for Compose, clearer fine-tuning failure classification, and RAG document deletion/management improvements
- `v0.7.6`: deterministic smoke fallback docs, workflow source selection across legacy and collection-managed RAG, and tighter inference readiness gating for selectable models
- `v0.7.7`: Docker/API/worker/Ollama runtime-validation scripts for stack smoke, inference, workflow model execution, collection-managed RAG workflow evidence, artifact-only model gating, RAG document CRUD refresh, PLC stub pipeline checks, and queue hardening

See `CHANGELOG.md` for the current milestone notes.
