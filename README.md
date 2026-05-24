# Domain-Adaptable AI Workflow Demo Platform

Mac-native FastAPI monolith for **MLX QLoRA fine-tuning with reviewer-curated RAG**. The headline loop:

1. Upload documents into a **RAG collection** (`/rag-collections`).
2. Ask LM Studio to generate **Q/A pairs** grounded in that collection (`POST /ft-datasets/from-rag-collection`).
3. Lock the dataset version and enqueue a real **MLX QLoRA** training job.
4. The trainer shells out to brew-installed `mlx_lm.lora` + `mlx_lm.fuse` and writes a fused MLX model under `data/model_artifacts/<job_id>/trainer_output/fused_model/`.
5. The publish flow symlinks the fused model into `~/.lmstudio/models/<namespace>/<name>/` and probes LM Studio. Once you load it in LM Studio, the platform flips the registry row from `artifact_ready` to selectable, and the new model becomes available through the OpenAI-compatible shim at `/v1/chat/completions`.

A static `/demo` console walks reviewers through a **3-step wizard**: Knowledge base → Train (optional) → Chat. Same screen, plain-language explainers, embedded chat. Power users can point [lobe-chat](https://github.com/lobehub/lobe-chat) or [Open WebUI](https://github.com/open-webui/open-webui) at `/v1/*` for a richer chat surface.

## Runtime shape (Mac-native)

- **Python 3.14** (`.python-version`).
- **Postgres** runs locally via `brew services start postgresql@16`. No `compose.yml`.
- **LM Studio** serves chat + embedding models locally at `http://127.0.0.1:1234/v1`. Load the chat model + (optional) embedding model in LM Studio's Local Server tab before starting the API.
- **brew `mlx-lm`** provides the `mlx_lm.lora` and `mlx_lm.fuse` CLIs the trainer shells out to.
- Single FastAPI app under `apps/api/` (uv workspace). No separate worker process — runner modules are dispatched in-process. Long-running MLX subprocesses stream their stdout/stderr directly to `data/model_artifacts/<job_id>/trainer_output/training.log`.

## Prerequisites

```bash
brew install postgresql@16 mlx mlx-lm uv
brew services start postgresql@16
createdb industrial_ai
```

Install [LM Studio](https://lmstudio.ai/) and load:

- a chat model (e.g. `lmstudio-community/Qwen2.5-7B-Instruct-MLX-4bit`)
- an embedding model (e.g. `mxbai-embed-large-mlx`) for collection retrieval previews

## Quick start

```bash
uv sync --dev

export API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai
export LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
export LMSTUDIO_CHAT_MODEL=lmstudio-community/Qwen2.5-7B-Instruct-MLX-4bit
export LMSTUDIO_EMBED_MODEL=mxbai-embed-large-mlx

uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/demo`, or hit the API directly:

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/v1/models
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
# ~/.lmstudio/models/ and probes LM Studio's /v1/models. Load the model in
# LM Studio (UI) and the registry row flips to selectable.
curl -s -X POST http://127.0.0.1:8000/ft-training-jobs/$(echo "$JOB" | jq -r .id)/publish
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

The `jobs` table is the queue and lifecycle source of truth (`queued → running → succeeded/failed`). `ft_training_jobs` has a richer phase model (`queued → preparing_data → training → packaging → registering → succeeded/failed`). There is no separate worker process; runner modules are dispatched in-process. Long MLX subprocesses stream stdout/stderr directly to `training.log` to keep memory bounded.

### Readiness gating

`artifact_ready` (reviewable, not selectable) → `publish_ready` (manifest exists) → `selectable` (LM Studio reports the fused model loaded). The platform places the fused model under `~/.lmstudio/models/<MLX_MODEL_NAMESPACE>/<name>/` (defaults to `demo/<job_id>` when `MLX_MODEL_NAMESPACE` is unset) but does not auto-load — you click "Load" in LM Studio's UI, then the platform's probe (which drops its 30s cache before each publish call) flips the registry row to `published`/`selectable`.

`base_model_name` (user-facing serving lineage), `trainer_model_name` (the actual MLX/HF checkpoint used by `mlx_lm.lora`), and `display_name` are intentionally distinct.

## Commands

```bash
uv run pyright -p pyrightconfig.json
uv run --project apps/api pytest -q apps/api/tests
uv run --project apps/api pytest -q apps/api/tests/test_ft_training_runner.py
uv run --project apps/api pytest -q apps/api/tests/test_ft_dataset_from_rag.py
./scripts/e2e_run_all.sh   # requires API + LM Studio running
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
│  │     ├─ demo/              # vanilla JS reviewer UI (Fine-tuning is the landing mode)
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
- LM Studio model loading is manual (platform symlinks the fused model + probes; LM Studio UI loads it)
- collection-managed RAG previews use extracted text, not a full per-collection embedding/index lifecycle
- async background job runner is deferred — `complete_training_job` currently runs synchronously when invoked
- markitdown for richer doc parsing is deferred until Python 3.14 onnxruntime wheels exist

## Versioning

- **v0.9.0** (2026-05-23): drop PLC slice + legacy `rag.db` workflow source; rename `ollama_model_name` DB column → `serving_model_name`; add dataset-from-RAG-collection endpoint; LM Studio auto-register fused model; real LM Studio SSE passthrough.
- **v0.8.0** (2026-05-23): Mac-native transition (drop Docker, drop separate worker process, drop Ollama clients, switch serving to LM Studio, MLX QLoRA via brew `mlx-lm`).
- See `CHANGELOG.md` for prior milestones.
