# Mac-Native Transition Plan

> Status: **COMPLETED** (2026-05-23). Retained as historical record of the migration scope. See `CHANGELOG.md` v0.8.0 for the executed changes.
>
> Generated: 2026-05-22
> Based on: Thorough review of entire codebase + delegated analysis from Claude and GPT

## Current State

The project is mid-transition after 4 commits (May 21, 2026) that made the right architectural decisions:
- Removed worker container (`apps/worker/`)
- Swapped torch/peft for brew mlx-lm MLX QLoRA
- Bumped Python to 3.14
- Added LM Studio client alongside Ollama

However, the codebase still reads like a Docker multi-OS platform. ~26 stale references across 22+ files,
orphaned data models, outdated documentation, and naming debt remain.

---

## Priority 1 — Fix Broken References to Removed Services

These reference services that literally don't exist anymore. They are **bugs**, not cleanups.

| # | File | Lines | Problem |
|---|------|-------|---------|
| 1.1 | `scripts/ft_smoke_preflight.sh` | 37-43 | `run_docker_preflight()` calls `docker compose exec -T worker` — worker service removed |
| 1.2 | `scripts/e2e_docker_stack_smoke.sh` | 67-109 | Checks for `worker` and `ollama` services that no longer exist in compose.yml |
| 1.3 | `scripts/e2e_workflow_real_model_smoke.py` | 56 | Guards against `"nvidia"` in error output from Docker Linux worker (removed) |
| 1.4 | `apps/api/src/api/services/rag/warmup_job_runner.py` | 49 | Tells users to run `docker compose exec -T ollama ollama pull` |
| 1.5 | `apps/api/src/api/services/workflows/service.py` | 73-111 | Every degraded-result path includes Docker-specific `rag-ingest` hint |
| 1.6 | `scripts/e2e_run_all.sh` | 15 | First step calls broken `e2e_docker_stack_smoke.sh` |
| 1.7 | `apps/api/src/api/static/demo/app.js` | 1000, 3068-3088 | UI hints reference "Docker worker", "MPS", "worker slot" |
| 1.8 | `apps/api/src/api/static/demo/index.html` | 585, 616-627 | UI text references "worker runtime", "Docker worker", `--worker-runtime docker` |

---

## Priority 2 — Structural Simplification

### 2.1 Remove `shared/` directory
- `shared/README.md` — explains why the directory is empty (never materialized)
- `shared/db/interface.py` — 15-line `JobRepository` Protocol, never used
- `pyrightconfig.json` — remove `shared/` paths
- **Rationale:** placeholder for multi-service future that never came. Single-app doesn't need this.

### 2.2 Remove `compose.yml`
- Now serves only one container (postgres:16)
- **Replace with:** `brew install postgresql@16 && brew services start postgresql@16` in README
- **Rationale:** Docker is unnecessary dependency for a single service. Adds friction to Mac-native path.

### 2.3 Remove `WorkerHeartbeatRecord` from models
- `apps/api/src/api/models.py:708-720` — orphaned table, worker is gone
- Keep the alembic migration for historical integrity

### 2.4 Consolidate LLM clients (`llm.py` + `embedding_client.py`)
- `OllamaChatClient` and `LMStudioChatClient` are 95% identical (both speak OpenAI `/v1/chat/completions`)
- Only difference: Ollama has fallback model chain (15 lines)
- **Replace with:** single `OpenAICompatibleChatClient(base_url, model, fallback_model?)`
- Same for embedding: `OllamaEmbeddingClient` + `LMStudioEmbeddingClient` → `OpenAICompatibleEmbeddingClient`
- **Saves:** ~200 lines of near-duplicate code

### 2.5 Consolidate `/admin` and `/demo` routes
- Both serve identical static files from `static/demo/`
- `/demo` has 80+ references; `/admin` was a failed rebranding (commit `f9a9623`)
- **Action:** Keep `/demo`, remove `/admin` mount in `main.py`

---

## Priority 3 — Naming Debt

| Current Name | New Name | Files Affected |
|---|---|---|
| `ollama_publish_enabled` | `adapter_publish_enabled` | `config.py`, `artifacts.py`,  `service.py`, `.env.example` |
| `ollama_model_namespace` | `mlx_model_namespace` | `config.py`, `artifacts.py`,  `.env.example` |
| `worker_runtime` (preflight) | `runner_runtime` or just `runtime` | `preflight.py`, `ft_smoke_preflight.sh` |
| `--worker-runtime docker` | Remove entirely | `preflight.py:480-485`, `ft_smoke_preflight.sh` |
| `FT_SMOKE_WORKER_RUNTIME` | `FT_SMOKE_RUNTIME` | `preflight.py` |
| `TRAINING_DEVICE=mps` | Remove (MLX auto-detects Metal) | `config.py`, `.env.example`, `preflight.py` |
| `FT_TRAINER_BACKEND=local_peft` | Already changed to `mlx_qlora` in code; fix `.env.example` | `.env.example` |
| `FT_DEFAULT_TRAINING_METHOD=sft_lora` | Already changed to `sft_qlora` in code; fix `.env.example` | `.env.example` |

---

## Priority 4 — Documentation Rewrite

### 4.1 README.md
Stale sections:
- "Quick Start With Docker Compose" (lines 332-386) — describes 4-container stack
- "Fine-tuning smoke runtime validation paths" (lines 170-240) — Docker, mixed, host profiles
- Worker subprocess docs (lines 130-134) — reference `torch`, `transformers`, `peft`, `datasets`, `accelerate`
- Repo structure (line 297) — lists `apps/worker/`
- "Architecture Summary" (lines 250-256) — lists `worker` as runtime service

### 4.2 docs/architecture.md
Stale sections:
- "Worker / Queue" (lines 25-34)
- Docker CPU smoke profile (lines 133-141)
- Runtime boundary docs (lines 144-160)

### 4.3 docs/runtime-validation.md
- Entire document assumes Docker stack prerequisites
- All commands reference `docker compose`

### 4.4 docs/skeleton-vs-service.md
- Line 22: "worker heartbeat and retry behavior" — remove

### 4.5 CHANGELOG.md
- Add v0.8.0 entry documenting the Mac-native transition

---

## Priority 5 — Consider for v1.0 (Flatten Monorepo)

With only one app remaining, the `apps/` directory is unnecessary indirection.

```
Before:                              After:
apps/api/src/api/          →        src/api/
apps/api/tests/            →        tests/
apps/api/pyproject.toml    →        pyproject.toml (merged into root)
proj.toml (just workspace) →        (removed)
shared/                    →        (removed)
```

Benefits:
- `PROJECT_ROOT` resolves as `parents[2]` instead of fragile `parents[4]`
- No uv workspace configuration overhead
- Simpler import paths

**Risk:** alembic paths, import paths, CI configuration. Not urgent.

---

## What Stays (Correctly Implemented)

- MLX training path (`trainer.py` — subprocess via brew `mlx_lm.lora` + `mlx_lm.fuse`)
- Preflight checker (brew mlx-lm detection, Metal validation)
- Error classifier (`service.py:_classify_training_failure()`)
- Model readiness gating (artifact-only vs selectable)
- `jobs` table state machine (keep for async tracking, just rename "worker" → "runner")
- Static demo UI (vanilla JS, single HTML — appropriate for demo scope)

---

## Execution Order

1. Fix broken references (Priority 1) — these are bugs
2. Remove `shared/` and `compose.yml` (Priority 2)
3. Rename config keys (Priority 3) — preserve env var backwards compat where possible
4. Unify LLM clients (Priority 2)
5. Update UI text in `app.js` and `index.html` (Priority 1/4)
6. Rewrite README and architecture docs (Priority 4)
7. Update test assertions to match new text (follows UI changes)
8. Add CHANGELOG v0.8.0 entry
