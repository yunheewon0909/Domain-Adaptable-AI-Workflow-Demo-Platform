# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo identity

Mac-native FastAPI monolith focused on **MLX QLoRA fine-tuning + RAG collections** backed by **LM Studio**. The legacy reviewer Workflow surface and the PLC test-automation slice are gone. Postgres is the queue and system of record (via `brew services start postgresql@16`). MLX QLoRA training runs locally via brew `mlx_lm.lora` and `mlx_lm.fuse`. Inference is served by LM Studio at `http://127.0.0.1:1234/v1`.

`uv` workspace, single member `apps/api`. Python **3.14** (`.python-version`). No `compose.yml`, no `apps/worker/`, no separate worker process — runner modules are dispatched directly by the API process / smoke scripts.

## Common commands

```bash
# Install workspace deps
uv sync --dev

# Run API (host)
export API_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/industrial_ai
export LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
export LMSTUDIO_CHAT_MODEL=lmstudio-community/Qwen2.5-7B-Instruct-MLX-4bit
export LMSTUDIO_EMBED_MODEL=mxbai-embed-large-mlx
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api uvicorn api.main:app --host 0.0.0.0 --port 8000

# Typecheck
uv run pyright -p pyrightconfig.json

# API tests
uv run --project apps/api pytest -q apps/api/tests

# Single test file / test
uv run --project apps/api pytest -q apps/api/tests/test_ft_training_runner.py
uv run --project apps/api pytest -q apps/api/tests/test_ai_ops_api.py::test_name

# Fine-tuning smoke (host MLX)
./scripts/ft_smoke_preflight.sh       # validates brew mlx-lm CLIs + Metal + LM Studio probe
./scripts/ft_smoke_test.sh            # creates dataset/version/rows, locks, enqueues sft_qlora
```

## Architecture

### Shape

Slim FastAPI app composed of small routers under `apps/api/src/api/routers/`:

- `fine_tuning`, `models` — AI ops slice (datasets → training jobs → model registry → inference)
- `rag` — collection-managed RAG (collections + documents + retrieval preview)
- `jobs` — generic queue read endpoints
- `openai_compat` — `/v1/models` + `/v1/chat/completions` shim, readiness-gated to selectable registry rows, with real LM Studio SSE passthrough
- `openwebui` — serves importable Open WebUI tool artifact + manifest
- `demo` — static reviewer UI at `/demo` (Fine-tuning is the default landing mode)
- `health`

### Queue

`jobs` table is the queue and lifecycle source of truth (`queued → running → succeeded/failed`). `ft_training_jobs` has a richer phase model: `queued → preparing_data → training → packaging → registering → succeeded/failed`. **No separate worker process.** A background asyncio dispatcher (`services/background_runner.py`) starts in the FastAPI lifespan, polls the `jobs` table for dispatchable types (currently `ft_train_model`), and runs the runner via `asyncio.to_thread()` so the event loop stays responsive during the multi-minute MLX subprocess. Tests force `FT_BACKGROUND_DISPATCH=false` so the TestClient never races with the trainer subprocess.

### Service slices (`apps/api/src/api/services/`)

- `fine_tuning/` — dataset/version/row management (`service.py`), Q/A pair generation from RAG collections (`qa_generator.py`), trainer-ready JSONL export (`dataset_formatters.py`, `artifacts.py`), trainer config + subprocess driver to brew `mlx_lm.lora` and `mlx_lm.fuse` (`trainer.py`), runtime preflight (`preflight.py`)
- `model_registry/` — registry CRUD + `ensure_default_models`, `job_runner.py` orchestrating dataset export → trainer → artifact registration, `lmstudio_register.py` placing fused MLX models into `~/.lmstudio/models/<namespace>/<name>/` and probing `/v1/models` to flip rows from `artifact_ready` to selectable
- `rag/` — `collections.py` for collection/document management + retrieval preview (only RAG path; legacy `rag.db` ingest/query/loader/chunker/embedder/reindex_runners removed)
- `jobs.py` — shared queue helpers
- `starter_definitions.py` — picks the active "starter" (app title + demo enablement)

### Readiness gating (load-bearing)

The Models surface and `/v1/models` shim split readiness deliberately:

- `artifact_ready` — adapter/report/manifest validated, **reviewable**, **not selectable**
- `publish_ready` — publish manifest/template exists, still not a real serving model
- `selectable` / runtime-ready — only when LM Studio reports the model loaded via `/v1/models`

Fine-tuned rows transition `artifact_ready → published`/`selectable` automatically once the publish flow's LM Studio probe sees the fused model loaded. The user still has to click "Load" in LM Studio's UI — the platform places the model dir under `~/.lmstudio/models` but does not auto-load.

`base_model_name` (user-facing serving lineage), `trainer_model_name` (actual MLX/HF checkpoint used by `mlx_lm.lora`), and `display_name` are intentionally distinct — a smoke run may legitimately train on a tiny model under a large `base_model_name` label, but that does not mean the serving model was fine-tuned.

### Headline feature: dataset-from-RAG-collection

`POST /ft-datasets/from-rag-collection` takes a `rag_collection_id`, chunks the collection's document `text_preview` fields, asks LM Studio to emit JSON Q/A pairs per chunk, and writes the pairs as `ft_dataset_rows`. Lives in `apps/api/src/api/services/fine_tuning/qa_generator.py`. End-to-end loop: upload docs → build dataset → lock version → enqueue `sft_qlora` → register fused model in LM Studio.

### Trainer subprocess

`_run_mlx_qlora_training` streams `mlx_lm.lora` / `mlx_lm.fuse` stdout+stderr directly to `data/model_artifacts/<job_id>/trainer_output/training.log` (Popen with file redirect) so memory stays bounded for long runs. Raises `RuntimeError` for missing CLIs (caught as `dependency_missing`), missing adapter weights (`mlx_subprocess_failed`), fuse non-zero exits (`mlx_subprocess_failed`), and empty `train_file` (early guard).

### Demo UI

Vanilla JS + single HTML at `apps/api/src/api/static/demo/`. Three reviewer modes: **Fine-tuning** (default), Models, RAG. No build step. PLC + Workflow modes were removed in v0.9.0; the JS file still contains orphan helper functions for them — harmless since the UI buttons + DOM ids are gone (`renderMode` has defensive `if (dom.workflowMode)` / `if (dom.plcMode)` guards).

### Open WebUI integration

Docker sidecar gone (ADR-0004 Superseded). Importable Python tool at `/openwebui/platform_tools.py` exposes RAG/models/FT read paths plus inference. Users running Open WebUI themselves point it at `/v1/*` and import the tool. Workflow tool methods were removed in v0.9.0.

## Conventions to keep

- Reuse the existing queue + runner subprocess pattern when adding a new domain. Don't introduce a second queue or a second frontend.
- New routers go under `apps/api/src/api/routers/` and get included in `main.py:create_app`. Default seed functions run in the lifespan startup branch (`ensure_default_models`, `ensure_default_rag_collections`).
- New alembic migrations: `apps/api/alembic/versions/`, follow existing date-prefix naming.
- `PROJECT_ROOT = Path(__file__).resolve().parents[4]` in `config.py` is fragile — touching the apps/api dir nesting breaks every relative path resolver.
- Smoke / fallback paths (`deterministic_smoke` trainer) exist on purpose — don't replace them with a hard failure.
- LM Studio is the only supported serving runtime. Don't reintroduce Ollama clients/settings. If you need an alternative OpenAI-compatible runtime, add it as a second client behind the same `LLMClient` Protocol rather than branching the dependency injector.
- The MLX trainer assumes brew-installed `mlx_lm.lora` and `mlx_lm.fuse` on PATH. Don't add a torch/peft fallback — the deterministic smoke backend is the only sanctioned escape hatch.
- The `_serialize_model` API contract uses `serving_model_name` (not the legacy `ollama_model_name`). DB column was renamed in alembic `20260523_0014`.
- Open source uptake constraint: prefer libraries with >50k GitHub stars (llama.cpp, open-webui, markitdown). MLX-LM (~7k) is an authorized exception because it's Apple's official Mac QLoRA path with no >50k alternative.
