# Architecture

> **Target shape (migration in progress, 2026-06).** This describes the Docker-first Open WebUI
> Graph RAG / evaluation platform. The prior Mac-native MLX QLoRA shape is superseded; see
> `docs/open-webui-docker-migration.md` and ADRs 0006–0011.

## Runtime shape

Five containers wired by `compose.yml`:

- **`open-webui`** — primary chat UI; points its OpenAI connection at `api`'s `/v1/*`.
- **`api`** — FastAPI app: domain RAG/evaluation/report endpoints + OpenAI-compatible shim. Runs
  with the in-process dispatcher off (`FT_BACKGROUND_DISPATCH=false`).
- **`worker`** — same image as `api`, entrypoint `python -m api.worker`; runs the dispatcher loop
  for long jobs (graph indexing, evaluation runs).
- **`ollama`** — default chat + embedding runtime.
- **`postgres`** — system of record: knowledge graph, evaluation data, job queue, operational
  metadata.

The API and worker share `API_DATABASE_URL` and the same job-runner registry. Document bytes live
under `data/rag_collections/<collection>/<document>` (the `app_data` volume).

## Runtime adapter (`services/runtime/`)

`ChatRuntime` and `EmbeddingRuntime` protocols abstract all model calls.

- `OpenAICompatRuntime` — base; talks the OpenAI `/v1/*` dialect (covers Ollama `/v1`, LM Studio,
  any OpenAI-compatible endpoint).
- `OllamaRuntime` — subclass; native model listing via `/api/tags`. Chat + embeddings use
  Ollama's OpenAI-compatible `/v1/*` surface (so embeddings POST to `/v1/embeddings`).

Selected by `LLM_RUNTIME_PROVIDER` (default `ollama`), `LLM_BASE_URL`
(default `http://ollama:11434`), `LLM_CHAT_MODEL`, `LLM_EMBED_MODEL`. `LMSTUDIO_*` envs remain as
deprecated aliases for one release. Routers and services never talk to a runtime directly.

## Queue & worker

The `jobs` table is the queue and lifecycle source of truth (`queued → running →
succeeded/failed`). `services/background_runner.py` claims rows with `SELECT … FOR UPDATE SKIP
LOCKED` (Postgres) or an in-process `asyncio.Lock` (sqlite tests) and dispatches to the runner
registered for the job type. In compose, only the `worker` container runs the loop; the `api`
container sets `FT_BACKGROUND_DISPATCH=false`. Current job types: `rag_index_collection` and
`evaluation_run`.

## Graph RAG

Lean in-repo GraphRAG — Postgres property graph + `networkx`, not Microsoft's `graphrag` package.

### Tables

- `rag_collections`, `rag_documents` (existing) + `rag_chunks`
- `rag_entities`, `rag_relationships`, `rag_entity_chunks` (entity→chunk provenance)
- `rag_communities`, `rag_community_members`
- `rag_query_traces` (persisted retrieval evidence for evaluation)

Embeddings are stored as JSON; cosine is computed in pure Python at demo scale. `pgvector` is an
optional advanced toggle, not the default.

### Index lifecycle (worker job)

`parse → chunk → embed_chunks → extract_graph → detect_communities → summarize_communities`.

- **extract_graph** — per chunk the chat runtime returns JSON `{entities, relationships}`;
  entities merge by normalized name across chunks with provenance recorded in `rag_entity_chunks`.
- **detect_communities** — build the per-collection graph in `networkx`, run
  `greedy_modularity_communities`, persist communities.
- **summarize_communities** — the chat runtime summarizes each community (title + summary) for
  global search; the summary is embedded.

### Retrieval

- **local** (default) — embed query → seed chunks/entities → 1–2 hop expansion over
  `rag_relationships` → gather connected chunks + relationships + relevant community summaries →
  grounded context + full trace.
- **global** — map-reduce over community summaries for broad questions.
- **naive** — chunk-vector retrieval fallback before the graph is built.

Every retrieval writes a `rag_query_traces` row (chunk/entity/relationship/community ids, scores,
excerpts, embedding model) — the substrate for evaluation.

## Evaluation (`services/evaluation/`)

- **Generation** — the former Q/A generator produces reviewable `evaluation_questions` (status
  accept/reject/edit) linked to `source_chunk_id` / `source_entity_id`.
- **Runs** — `evaluation_runs` execute retrieval + answer per question via the runtime adapter,
  score groundedness against stored traces, compute source coverage, and flag ungrounded claims
  into `evaluation_results`.
- **Reports** — aggregate collection health, retrieval quality, answer quality, source coverage,
  and graph stats (entity/relationship/community counts, density, orphan chunks). Surfaced to
  `/demo` and the Open WebUI tool.

## OpenAI-compatible shim

`GET /v1/models` and `POST /v1/chat/completions` proxy the configured runtime. Optional
`rag_collection_id` + `top_k` body fields ground a completion with document-level retrieval
(`preview_collection_retrieval`). This is what Open WebUI points at; plain OpenAI clients without
the extra fields get ordinary chat. Graph-mode retrieval (local/global/naive) lives on the
dedicated `POST /rag-collections/{id}/query` endpoint, not the chat shim.

## `/demo`

Admin / evaluation / debug dashboard only — **not** a chat UI. Lets a reviewer inspect
collections, trigger indexing, review evaluation sets, run evaluations, and read reports.

## Conventions

- Reuse the queue + worker for new long-running work; one queue, one worker.
- New routers under `apps/api/src/api/routers/`, included in `main.py:create_app`.
- New alembic migrations: date-prefixed under `apps/api/alembic/versions/`.
- All model calls go through `services/runtime/`.
- Container images use `python:3.12-slim`; code stays 3.11+ compatible.
- Graph algorithms use `networkx` (pure Python) — avoid native-dep graph libraries.
