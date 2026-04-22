# Runtime Validation

## Why this exists

The existing `pytest` coverage in this repository is intentionally strong on API contracts, deterministic service logic, worker/job state transitions, static reviewer UI strings, and smoke-fallback branches. It does **not** prove that the live Docker stack, worker subprocess execution, Ollama-backed inference, queue polling, collection-managed RAG workflow path, or artifact-only model gating all work together in one running environment.

The scripts in `scripts/e2e_*.py` and `scripts/e2e_*.sh` fill that gap.

## Test layers

### 1. Unit / contract tests

- location: `apps/api/tests/`, `apps/worker/tests/`
- fast and deterministic
- uses `TestClient`, monkeypatching, fake LLM/embedding clients, temp files, and local DB fixtures
- validates API schemas, readiness gating, fallback branches, worker queue logic, PLC deterministic execution rules, and static reviewer UI copy

### 2. Docker / API / worker E2E scripts

- location: `scripts/`
- calls the running API over HTTP
- polls real queue-backed jobs
- validates actual worker/job/result payloads
- validates real registry/readiness semantics and actual artifact paths written by the worker runtime

### 3. Browser E2E

- current status: **not configured in this repository yet**
- a Playwright skeleton is included only as a deferred placeholder so the intended happy path is recorded without pretending the repo already has a browser runner/toolchain wired up

## Prerequisites

### Always required

- workspace dependencies installed with `uv`
- API reachable at `API_BASE_URL` or the default `http://127.0.0.1:8000`

### Required for Docker/full-stack E2E

```bash
docker volume create ollama-models || true
docker compose up -d --build
```

### Required for real inference/workflow E2E

At least one `/models` entry must be `readiness.selectable == true`.

If no selectable model exists:

- default behavior: the inference-dependent E2E scripts **fail**
- opt-in skip behavior: set `E2E_ALLOW_NO_MODEL_SKIP=true`

This policy is intentionally strict by default because artifact-only `artifact_ready` / `publish_ready` rows are **not** runtime-ready models.

### Ollama model bootstrap

If the Docker stack is running but the serving models have not been pulled yet, use:

```bash
docker compose exec -T ollama ollama pull qwen2.5:3b-instruct-q4_K_M
docker compose exec -T ollama ollama pull qwen2.5:7b-instruct-q4_K_M
docker compose exec -T ollama ollama pull nomic-embed-text
```

## Script inventory

### `./scripts/e2e_docker_stack_smoke.sh`

Validates:

- `docker compose up -d --build`
- `postgres`, `api`, `worker`, and `ollama` service state
- `GET /health`, `/demo`, `/models`, `/workflows`, `/rag-collections`, `/plc-targets`
- absence of obvious API/worker startup fatals in recent logs

Notes:

- missing Ollama **models** should not fail this script
- a dead/unreachable Ollama **service** should fail this script

### `python scripts/e2e_ollama_inference_smoke.py`

Validates:

- `/models` returns a selectable model
- `/inference/run` accepts the selected `model_id`
- the response has a non-empty answer
- the response model payload matches the selected registry row
- artifact-only fine-tuned rows are rejected for inference

### `python scripts/e2e_workflow_real_model_smoke.py`

Validates:

- `/workflows/{workflow_key}/jobs` accepts a real `model_id`
- `/jobs/{job_id}` reaches a terminal state
- successful results keep `meta.model_id` and `meta.selected_model`
- legacy `rag.db` missing returns a structured `RAG index is not ready` result instead of noisy subprocess failure
- invalid `model_id` is rejected

### `python scripts/e2e_rag_collection_workflow_smoke.py`

Validates:

- collection creation
- document upload
- workflow execution using `rag_collection_id` plus a selectable model
- result metadata keeps `source_type=rag_collection`, `rag_collection_id`, and `model_id`
- evidence references the uploaded document
- empty collection returns a graceful degraded result instead of a 500

### `python scripts/e2e_ft_smoke_fallback.py`

Validates:

- dataset/version/row creation through the live API
- `validated -> locked` transitions
- queue-backed FT job polling through `/ft-training-jobs/{id}`
- adapter/report/log/publish-manifest artifact paths
- registered model state remains `artifact_ready` / `publish_ready` and **not selectable**

Important nuance:

- if the worker runtime really hits the smoke fallback path, the script confirms `artifact_validation.smoke_fallback_used == true`
- if the runtime completes the real `local_peft` path directly, the script reports that honestly instead of pretending the fallback was used

### `python scripts/e2e_model_gating_smoke.py`

Validates:

- an artifact-only fine-tuned model exists or can be created through the FT smoke path
- `/inference/run` rejects that `model_id`
- `/workflows/{workflow_key}/jobs` rejects that `model_id`
- artifact-only model IDs do not appear among selectable rows

### `python scripts/e2e_rag_document_management.py`

Validates:

- collection creation
- document upload/list/detail
- retrieval preview includes the uploaded document
- delete endpoint removes the document
- detail returns 404 after delete
- list and retrieval preview no longer show the deleted document

### `python scripts/e2e_plc_stub_pipeline.py`

Validates:

- CSV import through `/plc-testcases/import`
- suite and testcase list visibility
- `stub-local` target availability
- queue-backed PLC run enqueueing and polling
- run summary, run items, and IO-log endpoints

Important nuance:

- this is a deterministic stub executor path
- it is **not** an LLM inference path

### `python scripts/e2e_job_queue_processing.py`

Validates:

- two workflow jobs, one PLC run, and one FT smoke job can all be enqueued together
- they each reach terminal state
- no polled job remains stuck in `queued` or `running`

### `./scripts/e2e_run_all.sh`

Runs the main P0/P1 scripts in order:

1. Docker stack smoke
2. Ollama inference smoke
3. Workflow real-model smoke
4. RAG collection workflow smoke
5. FT smoke fallback
6. Model gating
7. RAG document management
8. PLC stub pipeline

## Recommended execution order

```bash
docker volume create ollama-models || true
docker compose up -d --build

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

Or use:

```bash
./scripts/e2e_run_all.sh
```

## Skip / fail policy

### No selectable model

- default: **fail** for inference-dependent scripts
- opt-in skip: `E2E_ALLOW_NO_MODEL_SKIP=true`

### Artifact-only model rows

- never treated as runtime-ready
- their presence is a **success case** for gating scripts, not a reason to bypass readiness rules

### Missing legacy `rag.db`

- workflow tests should treat a structured degraded result as success
- the bug being guarded here is noisy subprocess failure, not the absence of the index itself

### FT smoke fallback

- success is artifact-pipeline correctness and truthful registry state
- the script does **not** claim model quality or Ollama-serving readiness

## Troubleshooting

### `/health` never becomes ready

- inspect `docker compose ps`
- inspect `docker compose logs api --tail 100`
- confirm Postgres is healthy and migrations completed

### Inference/workflow smoke fails with no selectable model

- check `GET /models`
- confirm a base model is still `active` or `registered`
- if you intentionally want a non-blocking run in a model-less environment, export `E2E_ALLOW_NO_MODEL_SKIP=true`

### Ollama service is up but inference fails

- pull the expected serving model into the running Ollama runtime
- confirm the registry row still points at a serving model name that exists in that runtime

### FT smoke succeeds but no fallback was used

- that means the worker runtime completed the real `local_peft` path directly
- the script reports that honestly; it does not fake a fallback-only result

### PLC script fails

- confirm `stub-local` is present in `/plc-targets`
- confirm the imported suite produced testcase rows before enqueueing the run

### Playwright

- the repo does not currently include a configured Playwright toolchain
- use the included skeleton as a future checklist, not as an active passing browser suite today
