# ADR 0005: Narrow scope to Mac-native MLX QLoRA + collection-managed RAG (v0.8.0 + v0.9.0)

## Status

Accepted (2026-05-23).

## Context

The repo previously carried three parallel domains (legacy reviewer workflow on `rag.db`, PLC test automation, AI ops fine-tuning) and a multi-OS Docker stack (postgres + api + worker + ollama). Maintaining all three slices plus Docker portability was the bottleneck for the feature most users actually wanted: **QLoRA fine-tuning on Apple Silicon, grounded in reviewer-curated RAG documents, served back through LM Studio**.

## Decisions

### v0.8.0 — Mac-native runtime

1. **Drop Docker entirely.** Postgres runs via `brew services start postgresql@16`. `compose.yml` deleted. `apps/worker/` deleted.
2. **MLX QLoRA via brew `mlx-lm`.** Trainer subprocesses out to `mlx_lm.lora` (train) and `mlx_lm.fuse` (merge). The deterministic_smoke fallback is the only sanctioned escape hatch.
3. **LM Studio as the serving runtime.** All Ollama clients + settings deleted; LM Studio's OpenAI-compatible API is the only serving target.
4. **Python 3.14.** Older versions retired with the worker process.
5. **Lifespan replaces deprecated `on_event("startup")`** (Phase D1).

### v0.9.0 — Focus on the QLoRA-on-RAG loop

6. **Drop the PLC slice (Phase A1).** 8 ORM tables, services, routers, demo mode all removed. Alembic migration drops the tables + `jobs.plc_suite_id`. PLC was a parallel domain demo, not core to QLoRA+RAG.
7. **Drop the legacy `rag.db` workflow source (Phase A2).** `services/workflows`, `services/datasets`, `services/retrieval`, and legacy RAG ingest/query/sqlite_store/loader/chunker/embedder removed. The collection-managed RAG path (`services/rag/collections.py`) is the only RAG surface.
8. **Rename `model_registry.ollama_model_name` → `serving_model_name` (Phase A3).** Closes the last cosmetic tie to the dropped serving runtime.
9. **Dataset-from-RAG-collection endpoint (Phase B1).** Reviewers curate a RAG collection, then `POST /ft-datasets/from-rag-collection` asks LM Studio to emit grounded Q/A pairs and writes them as `ft_dataset_rows`. This is the headline feature.
10. **LM Studio auto-register fused model (Phase B3).** After `mlx_lm.fuse`, the publish flow symlinks the fused MLX bundle into `~/.lmstudio/models/<namespace>/<name>/` and probes LM Studio's `/v1/models`. When the user loads the model in LM Studio's UI, the registry row flips from `artifact_ready` → `selectable` automatically.
11. **Real LM Studio SSE passthrough (Phase D3).** `/v1/chat/completions` with `stream=true` proxies LM Studio's token chunks directly (id+model rewritten); not the previous buffered single-call wrapper.
12. **In-process background job dispatcher (Phase D2).** Started in lifespan; polls `jobs` for `ft_train_model` rows and runs the trainer via `asyncio.to_thread()` so the event loop stays responsive.

## Open source uptake (≥50k stars budget)

The user-supplied constraint was that adopted dependencies should have >50k GitHub stars where possible. The choices made:

| Library | Stars | Role | Status |
|---|---|---|---|
| `open-webui/open-webui` | ~80k | Optional external chat UX via `/v1/*` + the importable platform tool. | Documented integration |
| `ggerganov/llama.cpp` | ~75k | Documented as the optional GGUF conversion path (LM Studio reads MLX natively, so the trainer pipeline doesn't depend on llama.cpp). | Mentioned in docs |
| `microsoft/markitdown` | ~50k | Replacement for `pypdf` + custom loader in RAG ingestion. | **Deferred** — Python 3.14 incompatibility (markitdown's `magika` dep pulls `onnxruntime` which lacks 3.14 wheels) |
| `ml-explore/mlx-lm` | ~7k | Apple's official MLX QLoRA training path. | **Authorized exception** — no >50k alternative exists for Apple Silicon QLoRA training |

## Consequences

- The repo is now ~1/3 the size it was (PLC + legacy RAG + worker + Docker removed; +1674 / −14631 lines net).
- The remaining domain surface is small enough to read end-to-end in one sitting: `models.py` (ORM), `routers/{rag, fine_tuning, models, openai_compat}`, `services/{rag/collections, fine_tuning, model_registry}`.
- All quality gates (pyright, pytest) stay green; 129 tests cover the new shape.
- Dropping Docker means Mac-native users get a single `brew install` + `uv sync` + LM Studio. Non-Mac users have to bring their own Postgres + their own MLX-compatible Python; this is intentional.
- Background dispatcher unblocks the queue-backed FT path that previously sat in `queued` forever without an external worker. Multi-uvicorn-worker deployments are still warned to single-worker until Postgres-level row claim replaces the in-process asyncio lock.

## Superseded ADRs

- ADR 0001 (DB as system of record for PLC suites/runs) — PLC slice removed.
- ADR 0002 (Deterministic validator + CLI adapter) — PLC slice removed.
- ADR 0003 (Monorepo directory separation) — `apps/worker/` removed; single workspace member.
- ADR 0004 (Open WebUI sidecar) — Docker sidecar removed; importable tool retained.
