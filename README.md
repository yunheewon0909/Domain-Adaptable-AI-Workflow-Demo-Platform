# Domain-Adaptable AI Workflow Demo Platform

Mac-native FastAPI monolith for **MLX QLoRA fine-tuning with reviewer-curated RAG**. The headline loop:

1. Upload documents into a **RAG collection** (`/rag-collections`).
2. Ask LM Studio to generate **Q/A pairs** grounded in that collection (`POST /ft-datasets/from-rag-collection`).
3. Lock the dataset version and enqueue a real **MLX QLoRA** training job.
4. The trainer shells out to brew-installed `mlx_lm.lora` + `mlx_lm.fuse` and writes a fused MLX model under `data/model_artifacts/<job_id>/trainer_output/fused_model/`.
5. The publish flow symlinks the fused model into `~/.lmstudio/models/<namespace>/<name>/` and attempts to auto-load it via the `lms` CLI. Once LM Studio reports the model loaded, the platform flips the registry row to selectable and the new model is reachable through the OpenAI-compatible shim at `/v1/chat/completions`. If auto-load can't find it yet, load it manually in LM Studio — the registry row self-heals on the next model listing.
6. Optionally **verify** the result: an LLM-as-Judge scores the fine-tuned model against its base, with and without RAG (Step 5).

A static `/demo` console walks reviewers through a wizard: **Knowledge base → Generate Q&A pairs → Review & edit → Fine-tune → Verify → Chat** (steps 2–5 are optional). Same screen, plain-language explainers, embedded chat. Power users can point [lobe-chat](https://github.com/lobehub/lobe-chat) or [Open WebUI](https://github.com/open-webui/open-webui) at `/v1/*` for a richer chat surface.

## Runtime shape (Mac-native)

- **Python 3.14** (`.python-version`), managed by **uv** (workspace root `pyproject.toml`; the app package is `apps/api/`).
- **Postgres** runs locally via `brew services start postgresql@16`. No `compose.yml`.
- **LM Studio** serves chat + embedding models locally at `http://127.0.0.1:1234/v1`, and provides the `lms` CLI the platform uses to load/unload models. It is the only supported serving runtime.
- **brew `mlx-lm`** provides the `mlx_lm.lora` and `mlx_lm.fuse` CLIs the trainer shells out to.
- Single FastAPI app under `apps/api/` (uv workspace). No separate worker process: an in-process **background dispatcher** (started in the app lifespan, on by default) polls the queue and runs training jobs. Long-running MLX subprocesses stream their stdout/stderr directly to `data/model_artifacts/<job_id>/trainer_output/training.log`.

## Starting the service (runbook for humans and agents)

Follow these steps in order. Each step is independently checkable.

### 1. Install host dependencies (one time)

```bash
brew install postgresql@16 mlx mlx-lm uv
brew services start postgresql@16
createdb industrial_ai          # ok if it already exists
uv sync --dev                   # run from the repo root
```

Install [LM Studio](https://lmstudio.ai/), then in its UI download + load:

- a **chat model** (e.g. `liquid/lfm2.5-1.2b` or `lmstudio-community/Qwen2.5-7B-Instruct-MLX-4bit`)
- an **embedding model** (e.g. `text-embedding-nomic-embed-text-v1.5`) for RAG retrieval previews

Confirm LM Studio's local server is up and lists your models:

```bash
curl -s http://127.0.0.1:1234/v1/models | jq -r '.data[].id'
```

### 2. Set environment variables

**The app does not read `.env` automatically** — you must export these in the shell that launches uvicorn (or wrap them inline on the command). `.env.example` documents every knob; the essentials:

```bash
export API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai
export LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
export LMSTUDIO_CHAT_MODEL=liquid/lfm2.5-1.2b              # must match an id loaded in LM Studio
export LMSTUDIO_EMBED_MODEL=text-embedding-nomic-embed-text-v1.5
export LMSTUDIO_TIMEOUT_SECONDS=1200                       # MLX generations can be slow
```

`LMSTUDIO_CHAT_MODEL` must exactly match an id from step 1's `curl` (case included) so it becomes the default selectable model on startup. `MLX_MODEL_NAMESPACE` defaults to `demo` (where published fine-tunes are placed under `~/.lmstudio/models/demo/`).

### 3. Apply migrations + launch the API

```bash
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000
```

To launch in the background and capture logs:

```bash
uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn.log 2>&1 &
```

> **Restart after editing Python.** The server runs without `--reload`. Static `/demo` assets are read from disk per request (cache-busted via `?v=N` in `index.html`), but changes to trainer/services/routers only take effect after restarting uvicorn. A stale server silently running old code is the #1 source of "my fix didn't work".

### 4. Verify it's up

```bash
curl -s http://127.0.0.1:8000/health                       # {"status":"ok"}
curl -s http://127.0.0.1:8000/v1/models | jq               # selectable models only
```

Then open the wizard at `http://127.0.0.1:8000/demo`.

### Stopping / restarting

```bash
pkill -f "uvicorn api.main:app"     # stop
# then re-run the launch command from step 3
```

## The headline flow: QLoRA on a curated RAG collection

```bash
# 1. Create a RAG collection + upload documents
COLLECTION=$(curl -s -X POST http://127.0.0.1:8000/rag-collections \
  -H 'Content-Type: application/json' \
  -d '{"name":"Maintenance handbook"}' | jq -r .id)

curl -s -X POST "http://127.0.0.1:8000/rag-collections/$COLLECTION/documents" \
  -F "file=@docs/maintenance.pdf;type=application/pdf"

# 2. Generate Q/A pairs from the collection
DATASET=$(curl -s -X POST http://127.0.0.1:8000/ft-datasets/from-rag-collection \
  -H 'Content-Type: application/json' \
  -d "{\"rag_collection_id\":\"$COLLECTION\",\"dataset_name\":\"Maintenance Q/A\",\"pairs_per_chunk\":3,\"max_chunks\":40}")
VERSION=$(echo "$DATASET" | jq -r .dataset_version_id)

# 3. Lock the dataset version, then enqueue MLX QLoRA training
curl -s -X POST "http://127.0.0.1:8000/ft-dataset-versions/$VERSION/status" \
  -H 'Content-Type: application/json' -d '{"status":"validated"}'
curl -s -X POST "http://127.0.0.1:8000/ft-dataset-versions/$VERSION/status" \
  -H 'Content-Type: application/json' -d '{"status":"locked"}'

JOB=$(curl -s -X POST http://127.0.0.1:8000/ft-training-jobs \
  -H 'Content-Type: application/json' \
  -d "{\"dataset_version_id\":\"$VERSION\",\"base_model_name\":\"qwen2.5:7b-instruct-q4_K_M\",\"hyperparams_json\":{\"trainer_model_name\":\"mlx-community/Qwen2.5-0.5B-Instruct-4bit\"}}")

# 4. Watch progress
curl -s http://127.0.0.1:8000/ft-training-jobs/$(echo "$JOB" | jq -r .id)

# 5. After training, publish — the platform symlinks the fused model into
# ~/.lmstudio/models/ and tries to auto-load it via the lms CLI. If auto-load
# can't find it yet, load it in LM Studio (UI); the registry row self-heals to
# selectable on the next model listing.
curl -s -X POST http://127.0.0.1:8000/ft-training-jobs/$(echo "$JOB" | jq -r .id)/publish

# 6. (optional) Verify FT vs base with an LLM-as-Judge — poll for the result
VJOB=$(curl -s -X POST http://127.0.0.1:8000/inference/verify-job \
  -H 'Content-Type: application/json' \
  -d "{\"verifier_model\":\"$LMSTUDIO_CHAT_MODEL\",\"fine_tuned_model\":\"<published_name>\",\"base_model\":\"$LMSTUDIO_CHAT_MODEL\",\"question\":\"<an in-domain question>\"}" | jq -r .job_id)
curl -s http://127.0.0.1:8000/inference/verify-job/$VJOB | jq
```

## Fine-tuning smoke test (tiny, artifact-only)

```bash
./scripts/ft_smoke_preflight.sh   # checks brew mlx-lm CLIs + Metal + LM Studio + artifact dir
./scripts/ft_smoke_test.sh        # creates dataset/rows/lock/enqueue with a tiny trainer model
```

After completion:

```bash
ls data/model_artifacts/<job_id>/trainer_output/
# adapters/  adapters.safetensors  fused_model/  training_report.json  training.log
```

The smoke flow validates the **artifact pipeline**, not model quality. Smoke jobs use `hf-internal/testing-tiny-random-gpt2` as the trainer model and stay in `artifact_ready` until LM Studio actually loads the fused model.

## OpenAI-compatible shim (`/v1/*`)

The `model` values below (`Qwen2.5 7B - default platform model`) are illustrative — the exposed id is derived from whatever you loaded as `LMSTUDIO_CHAT_MODEL`. Always read the real id from `GET /v1/models` first; with the runbook's `liquid/lfm2.5-1.2b` it surfaces as `liquid/lfm2.5-1.2b - default platform model`.

```bash
curl -s http://127.0.0.1:8000/v1/models | jq

# Non-streaming
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen2.5 7B - default platform model",
    "messages": [{"role":"user","content":"What is this platform for?"}],
    "max_tokens": 64
  }'

# Streaming — real LM Studio SSE chunks proxied through (id+model rewritten)
curl -N -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen2.5 7B - default platform model","messages":[{"role":"user","content":"explain LoRA"}],"stream":true}'

# Optional RAG grounding via custom body field
curl -s -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen2.5 7B - default platform model",
    "messages": [{"role":"user","content":"summarize maintenance evidence"}],
    "rag_collection_id": "rag-collection-1",
    "top_k": 4
  }'
```

Limits: usage token counts are placeholders, only `readiness.selectable == true` rows are exposed, no tool/function calling, no `n>1`, no `logprobs`.

## Architecture

### Routers (`apps/api/src/api/routers/`)

- `fine_tuning`, `models` — datasets → training jobs → model registry → inference
- `rag` — collection-managed RAG (collections + documents + retrieval preview)
- `jobs` — generic queue read endpoints
- `openai_compat` — `/v1/models` + `/v1/chat/completions` (real LM Studio SSE passthrough)
- `openwebui` — serves importable Open WebUI tool artifact + manifest
- `demo` — static reviewer UI
- `health`

### Queue

The `jobs` table is the queue and lifecycle source of truth (`queued → running → succeeded/failed`). `ft_training_jobs` has a richer phase model (`queued → preparing_data → training → packaging → registering → succeeded/failed`) and a `backing_job_id` pointing at its `jobs` row. There is no separate worker process: an in-process **background dispatcher** (started in the app lifespan, on by default, set `FT_BACKGROUND_DISPATCH=false` to disable — tests do) polls the queue and runs jobs. Long MLX subprocesses stream stdout/stderr directly to `training.log` to keep memory bounded.

### Readiness gating

`artifact_ready` (reviewable, not selectable) → `publish_ready` (fused model + manifest on disk) → `published`/`selectable` (LM Studio reports the fused model loaded). The platform places the fused model under `~/.lmstudio/models/<MLX_MODEL_NAMESPACE>/<name>/` (namespace defaults to `demo`) and **attempts to auto-load it via the `lms` CLI** during publish, retrying discovery a few times in case LM Studio hasn't indexed the new directory yet. If auto-load can't find it, load it manually in LM Studio — `list_models`/`get_model` probe the loaded set and **self-heal** a `publish_ready` row to `published` once its name shows up loaded (the chat path rejects non-selectable rows with the row's `selectable_reason`).

`base_model_name` (user-facing serving lineage), `trainer_model_name` (the actual MLX/HF checkpoint used by `mlx_lm.lora`), and `published_model_name`/`serving_model_name` (what LM Studio serves it as) are intentionally distinct — don't conflate them. When resolving a base model to train from, the platform excludes the publish namespace so a retrain never trains on top of a previously published fine-tune.

### Step 5 verification (LLM-as-Judge)

`POST /inference/verify-job` runs four inferences — fine-tuned and base, each with and without RAG — then has a judge model score them 0–10 (`GET /inference/verify-job/{id}` to poll). It also reports FT-vs-base answer similarity and warns when they're near-identical. On a small base model, out-of-domain questions produce identical greedy output (expected, not a routing bug), so the demo suggests in-domain questions drawn from the fine-tune's training data.

## Commands

```bash
# Type check (basic mode; pyright is the only configured linter)
uv run pyright -p pyrightconfig.json

# Tests — sqlite-backed and LM-Studio-faked, so no Postgres/LM Studio needed
uv run --project apps/api pytest -q apps/api/tests                     # all
uv run --project apps/api pytest -q apps/api/tests/test_ft_training_runner.py   # one file
uv run --project apps/api pytest -q "apps/api/tests/test_openai_compat.py::test_v1_models_exposes_only_selectable_rows"  # one test

# Smoke + E2E — these require the API + LM Studio actually running
./scripts/ft_smoke_preflight.sh   # checks mlx-lm CLIs, Metal, LM Studio, artifact dir
./scripts/ft_smoke_test.sh        # tiny artifact-only training run
./scripts/e2e_run_all.sh
```

## Open WebUI integration

Run Open WebUI yourself (Docker Desktop, brew, etc.) and:

- point its OpenAI base URL at `http://127.0.0.1:8000/v1`
- import the platform tool: `curl http://127.0.0.1:8000/openwebui/platform_tools.py`
- `GET /openwebui/manifest.json` lists the exposed methods (RAG, Models, FT — workflow methods removed in v0.9.0)

## Open source uptake (>50k stars credit)

| Lib | Stars | Role |
|---|---|---|
| `ggerganov/llama.cpp` | ~75k | Mentioned as the optional GGUF conversion path for users who want non-MLX serving |
| `open-webui/open-webui` | ~80k | Optional chat UX through `/v1/*` + the importable tool |
| `microsoft/markitdown` | ~50k | **Deferred** — blocked by Python 3.14 / `onnxruntime` wheel availability. PDF text extraction stays on `pypdf` for now. |

Authorized exception: `ml-explore/mlx-lm` (~7k stars). Apple's official MLX QLoRA path; no >50k alternative exists for Apple Silicon QLoRA training.

## Repo layout

```text
.
├─ apps/api/
│  ├─ alembic/versions/        # date-prefixed migrations
│  ├─ src/api/
│  │  ├─ routers/              # demo, fine_tuning, health, jobs, models, openai_compat, openwebui, rag
│  │  ├─ services/
│  │  │  ├─ fine_tuning/       # dataset/version/row + qa_generator (RAG → Q/A) + MLX trainer + preflight
│  │  │  ├─ model_registry/    # CRUD + job_runner + lmstudio_register (auto-place fused model)
│  │  │  └─ rag/               # collections.py (only RAG path)
│  │  └─ static/
│  │     ├─ demo/              # vanilla JS reviewer UI (wizard: KB → Q&A → review → fine-tune → verify → chat)
│  │     └─ openwebui/         # importable Open WebUI tool artifact
│  └─ tests/
├─ scripts/                    # smoke + E2E entrypoints
├─ data/                       # sample datasets, RAG collections, generated model_artifacts
├─ docs/                       # architecture, ADRs, transition history
├─ examples/                   # demo datasets
├─ pyproject.toml              # uv workspace root
└─ uv.lock
```

## Conventions

- Reuse the existing queue + runner subprocess pattern for new domains. Don't introduce a second queue or a second frontend.
- New routers go under `apps/api/src/api/routers/` and get included in `main.py:create_app`. Default seeds run in the `lifespan` startup branch.
- New alembic migrations: `apps/api/alembic/versions/`, date-prefixed.
- The trainer assumes brew-installed `mlx_lm.lora` and `mlx_lm.fuse` on PATH. The `deterministic_smoke` backend is the only sanctioned escape hatch — keep it.
- LM Studio is the only supported serving runtime. Don't reintroduce Ollama clients.

## Limitations

- no auth / multi-user
- LM Studio model loading is best-effort: publish auto-loads the fused model via the `lms` CLI when it can discover it, otherwise you load it manually in LM Studio and the registry row self-heals on the next listing
- collection-managed RAG previews use extracted text, not a full per-collection embedding/index lifecycle
- verify-job state is in-memory (`_verify_jobs`), so an in-flight Step 5 run is lost on server restart — the UI surfaces this and stops polling rather than hanging
- markitdown for richer doc parsing is deferred until Python 3.14 onnxruntime wheels exist

## Versioning

- **Unreleased** (2026-06): publish auto-loads the fused model via the `lms` CLI and `publish_ready` rows self-heal to selectable once LM Studio reports them loaded; Step 5 LLM-as-Judge verification (`/inference/verify-job`); human-readable model naming; small-dataset training auto-scales iters/LR; base-model resolution excludes the publish namespace so retrains don't train on a prior fine-tune.
- **v0.9.0** (2026-05-23): drop PLC slice + legacy `rag.db` workflow source; rename `ollama_model_name` DB column → `serving_model_name`; add dataset-from-RAG-collection endpoint; LM Studio auto-register fused model; real LM Studio SSE passthrough.
- **v0.8.0** (2026-05-23): Mac-native transition (drop Docker, drop separate worker process, drop Ollama clients, switch serving to LM Studio, MLX QLoRA via brew `mlx-lm`).
- See `CHANGELOG.md` for prior milestones.
