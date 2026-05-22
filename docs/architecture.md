# Architecture

## Current shape (v0.9.0)

Mac-native FastAPI monolith. Single uv workspace member (`apps/api`). No `compose.yml`, no separate worker process. Postgres runs locally via `brew services start postgresql@16`. LM Studio at `http://127.0.0.1:1234/v1` serves chat + embedding models. The trainer subprocess shells out to brew `mlx_lm.lora` + `mlx_lm.fuse`.

The repo is intentionally narrow: **MLX QLoRA fine-tuning + collection-managed RAG**. The legacy reviewer Workflow surface and the PLC test-automation slice were removed in v0.9.0 to keep the codebase focused.

Postgres is still the system of record for the queue and operational metadata. RAG document content (`text_preview` + the stored file bytes) lives in `rag_documents.metadata_json` and `data/rag_collections/<collection>/<document>`.

## Routers (`apps/api/src/api/routers/`)

- `fine_tuning` — dataset CRUD, version status transitions, training enqueue, **dataset-from-RAG-collection** Q/A generator
- `models` — registry inspection, lineage, artifact/log access, publish (places fused model under `~/.lmstudio/models/` + probes LM Studio), inference
- `rag` — collection CRUD, document upload/delete, retrieval preview
- `jobs` — generic queue read endpoints (no PLC filter)
- `openai_compat` — `/v1/models` + `/v1/chat/completions` with real LM Studio SSE passthrough; readiness-gated to selectable registry rows
- `openwebui` — serves the importable Open WebUI tool artifact + manifest
- `demo` — static reviewer UI (vanilla JS, Fine-tuning is the landing mode)
- `health`

## Queue

The `jobs` table is the queue and lifecycle source of truth (`queued → running → succeeded/failed`). `ft_training_jobs` has a richer phase model: `queued → preparing_data → training → packaging → registering → succeeded/failed`. There is no separate worker process — runner modules are dispatched in-process (`api.services.model_registry.job_runner`). Long-running MLX subprocesses stream stdout/stderr directly to `data/model_artifacts/<job_id>/trainer_output/training.log` so memory stays bounded.

An async background dispatcher (Phase D2) is planned but not yet wired: today `complete_training_job` runs synchronously when invoked.

## AI ops slice

Tables:
- `ft_datasets`, `ft_dataset_versions`, `ft_dataset_rows`
- `ft_training_jobs`, `ft_model_artifacts`, `model_registry`
- `rag_collections`, `rag_documents`

End-to-end loop:

1. Create a RAG collection and upload documents (`POST /rag-collections`, `POST /rag-collections/{id}/documents`).
2. Generate a fine-tuning dataset from the collection (`POST /ft-datasets/from-rag-collection`). The Q/A generator chunks the document `text_preview`, asks LM Studio for strict-JSON `{"question":..., "answer":...}` pairs per chunk, and writes them as `ft_dataset_rows` with `input_json={"instruction":..., "input":""}`, `target_json={"output":...}`.
3. Lock the dataset version (`POST /ft-dataset-versions/{id}/status`).
4. Enqueue training (`POST /ft-training-jobs`). The trainer exports JSONL under `data/model_artifacts/<job_id>/dataset_export/`, runs `mlx_lm.lora` → adapter weights, then `mlx_lm.fuse` → a fused MLX model dir.
5. Publish (`POST /ft-training-jobs/{id}/publish`). The platform symlinks the fused model dir into `~/.lmstudio/models/<MLX_MODEL_NAMESPACE>/<name>/` and probes LM Studio's `/v1/models`. If LM Studio reports the model loaded, the registry row flips from `artifact_ready` to `published`/`selectable` and shows up in `/v1/models`.

## Readiness gating

- `artifact_ready` — adapter/report/manifest validated; reviewable, **not** selectable
- `publish_ready` — publish manifest/template exists, fused model placed in LM Studio's models dir
- `published` / `selectable` — LM Studio reports the model loaded via `/v1/models` probe

`base_model_name` (user-facing serving lineage), `trainer_model_name` (actual MLX/HF checkpoint used by `mlx_lm.lora`), and `display_name` are intentionally distinct.

## Smoke fallback

`deterministic_smoke` backend produces a placeholder adapter package without invoking MLX. Used when `FT_ALLOW_SMOKE_FALLBACK=true` and the configured trainer model fails to resolve (HF download error). Validates the artifact pipeline only — not model quality.

## OpenAI-compatible shim

`GET /v1/models` lists only `readiness.selectable == true` rows.

`POST /v1/chat/completions`:
- non-streaming: buffered single response
- streaming (`stream: true`): real LM Studio SSE chunks proxied through; `id` and `model` are rewritten to the platform's exposed identifiers; a trailing platform-metadata chunk + `data: [DONE]` are appended

Optional `rag_collection_id` + `top_k` body fields ground a completion with platform-managed RAG evidence. Plain OpenAI clients that don't send these fields get ordinary registry-gated chat.

## RAG slice

Only `services/rag/collections.py` and `services/rag/embedding_client.py` remain. PDF text extraction uses `pypdf`. Markitdown (microsoft, ~50k stars) is deferred until Python 3.14 `onnxruntime` wheels exist.

## Conventions

- Reuse the existing queue + runner subprocess pattern when adding a new domain.
- New routers under `apps/api/src/api/routers/`, included in `main.py:create_app`.
- New alembic migrations: date-prefixed, under `apps/api/alembic/versions/`.
- `PROJECT_ROOT = Path(__file__).resolve().parents[4]` is fragile — touching `apps/api/` nesting breaks every relative path resolver.
- The trainer assumes brew-installed `mlx_lm.lora` + `mlx_lm.fuse` on PATH. The `deterministic_smoke` backend is the only sanctioned escape hatch.
- LM Studio is the only supported serving runtime; don't reintroduce Ollama.
- API contract uses `serving_model_name` (DB column renamed from `ollama_model_name` in alembic `20260523_0014`).

## Why this still fits a "skeleton"

The architectural backbone (FastAPI app + Postgres queue + co-hosted reviewer UI + readiness-gated OpenAI shim) is unchanged. v0.9.0 removed two domain slices (PLC, legacy Workflow) and one DB-column rename, but the queue/runner/registry pattern that survives is still the substrate for adding new domains.
