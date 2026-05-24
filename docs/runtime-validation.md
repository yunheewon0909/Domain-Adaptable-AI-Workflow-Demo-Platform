# Runtime Validation

## Why this exists

The `pytest` suites under `apps/api/tests` cover API contracts, deterministic service logic, queue state transitions, static reviewer UI strings, the SSE passthrough, and the QA generator. They do **not** prove that the live API + LM Studio + MLX subprocess execution + LM Studio model loading all work together end-to-end.

The scripts in `scripts/e2e_*.py` and `scripts/e2e_*.sh` fill that gap.

## Test layers

### 1. Unit / contract tests

- location: `apps/api/tests/`
- fast and deterministic
- uses `TestClient`, monkeypatching, fake LLM/embedding clients, temp files
- validates API schemas, readiness gating, smoke-fallback branches, queue logic, static reviewer UI copy, SSE passthrough (with a fake LMStudioChatClient)

### 2. API E2E scripts

- location: `scripts/`
- calls the running API over HTTP
- polls real queue-backed jobs
- validates actual job/result payloads and artifact paths written by the trainer subprocess

### 3. Browser E2E

- not configured; a Playwright skeleton lives at `tests/e2e/playwright/demo_happy_path.spec.ts` as a placeholder

## Prerequisites

- workspace dependencies installed with `uv sync --dev`
- API reachable at `API_BASE_URL` or the default `http://127.0.0.1:8000`
- Postgres running locally (`brew services start postgresql@16` after `createdb industrial_ai`)
- LM Studio running with the chat + embedding models named in `LMSTUDIO_CHAT_MODEL` / `LMSTUDIO_EMBED_MODEL` loaded

### Required for real inference E2E

At least one `/models` entry must be `readiness.selectable == true`.

If no selectable model exists:
- default: inference-dependent scripts fail
- opt-in skip: `E2E_ALLOW_NO_MODEL_SKIP=true`

This policy is intentionally strict because `artifact_ready` / `publish_ready` rows are **not** runtime-ready.

## Script inventory

### `scripts/e2e_qlora_rag_dataset_smoke.py`

Headline QLoRA-on-RAG-collection feature:
- create a RAG collection + upload a small document
- `POST /ft-datasets/from-rag-collection` generates Q/A pairs via LM Studio
- confirms rows are written and dataset / version IDs come back

Requires LM Studio with the configured chat model loaded.

### `scripts/e2e_ft_smoke_fallback.py`

End-to-end FT smoke:
- dataset/version/row creation through the live API
- `validated → locked` transitions
- queue-backed FT job polling through `/ft-training-jobs/{id}`
- adapter/report/log/publish-manifest artifact paths
- registered model state stays `artifact_ready` / `publish_ready` until LM Studio loads the fused model

If the runtime hits the smoke fallback path, the script confirms `artifact_validation.smoke_fallback_used == true`. If the runtime completes the real `mlx_qlora` path directly, the script reports that honestly.

### `scripts/e2e_rag_document_management.py`

- collection creation, document upload/list/detail
- retrieval preview includes the uploaded document
- delete removes the document; detail returns 404 after

### `./scripts/e2e_run_all.sh`

Runs the three scripts above in order via `uv run --project apps/api python`. The Workflow / model-gating / job-queue scripts were removed with the v0.9.0 slice cull because they depended on the deleted `/workflows` surface.

## Recommended execution order

```bash
brew services start postgresql@16
# load the chat + embedding models in LM Studio

uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000 &

./scripts/e2e_run_all.sh
```

## Troubleshooting

### `/health` never becomes ready

- confirm `brew services list` reports postgresql@16 as `started`
- check uvicorn logs for migration errors
- confirm `API_DATABASE_URL` points at the running Postgres instance

### Inference E2E fails with no selectable model

- check `GET /models`
- confirm the loaded LM Studio model id matches `LMSTUDIO_CHAT_MODEL`
- if you intentionally want a non-blocking run, export `E2E_ALLOW_NO_MODEL_SKIP=true`

### LM Studio is up but `/v1/chat/completions` fails

- open LM Studio → Local Server tab; confirm the model is loaded and the server is started
- confirm `LMSTUDIO_BASE_URL` matches LM Studio's port (`curl http://127.0.0.1:1234/v1/models`)

### FT smoke succeeds but no fallback was used

- means the runtime completed the real `mlx_qlora` path directly
- script reports honestly; does not fake a fallback-only result

### Publish flips back to `publish_ready` immediately

- LM Studio is reachable but the configured `candidate_model_name` is not in `/v1/models`
- click "Load" in LM Studio's UI for the model dir under `~/.lmstudio/models/<MLX_MODEL_NAMESPACE>/<name>/`, then call publish again
