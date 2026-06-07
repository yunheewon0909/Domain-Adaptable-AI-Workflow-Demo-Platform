# Domain-Adaptable AI Workflow Demo Platform

A **Docker-first domain RAG + evaluation backend** that plugs into **Open WebUI**. Upload your
documents, build a **knowledge graph** over them (Graph RAG), chat with grounded answers in Open
WebUI, then **generate evaluation testsets and score retrieval/answer quality** — all from
`docker compose up`, with **Ollama** as the default local runtime. No Homebrew, no MLX, no LM
Studio required.

> **Migration in progress (2026-06).** This project was previously a Mac-native MLX QLoRA
> fine-tuning tool. It is being redirected to the Docker-first Open WebUI shape described here.
> See [`docs/open-webui-docker-migration.md`](docs/open-webui-docker-migration.md) for the plan
> and phase status.

## What it is (and isn't)

- **Primary UI: Open WebUI.** We do not ship a competing chat UI. The bundled `/demo` page is an
  **admin / evaluation / debug dashboard** only.
- **Default runtime: Ollama** (container) for both chat and embeddings. LM Studio, native
  Ollama, or any OpenAI-compatible endpoint can be plugged in via configuration — optional, never
  required.
- **Core capability: Graph RAG.** Documents are chunked, an LLM extracts an entity/relationship
  **knowledge graph**, communities are detected and summarized, and retrieval traverses the graph
  — every answer comes with a traceable evidence trail.
- **Evaluation, not fine-tuning.** Fine-tuning has been removed from the core. The Q/A generator
  now produces **reviewable evaluation testsets**, and the platform **scores** a collection's
  retrieval quality, answer groundedness, and source coverage — the thing that makes this more
  than plain Open WebUI RAG chat.

## Architecture

```
┌────────────┐     ┌────────────┐     ┌──────────────┐
│ Open WebUI │────▶│    api     │────▶│   postgres   │
│  (chat UI) │     │ (FastAPI)  │     │ (graph + ops)│
└────────────┘     └─────┬──────┘     └──────────────┘
                         │  ▲
                         ▼  │ shares DB + job queue
┌────────────┐     ┌────────────┐
│   ollama   │◀────│   worker   │  long-running index / eval jobs
│ (runtime)  │     │ (dispatch) │
└────────────┘     └────────────┘
```

Five containers: `postgres`, `ollama`, `open-webui`, `api`, `worker`. The API serves the domain
RAG/evaluation/report endpoints and an OpenAI-compatible shim (`/v1/*`) that Open WebUI points at.
The worker runs long jobs (graph indexing, evaluation runs) off the shared Postgres job queue.

## Quick start (Docker-only)

```bash
cp .env.example .env          # defaults already target the Ollama container
docker compose up -d --build
```

Then pull a model into the Ollama container and open the UIs:

```bash
docker compose exec ollama ollama pull llama3.2            # chat model
docker compose exec ollama ollama pull nomic-embed-text    # embedding model
```

| Service | URL | Notes |
| --- | --- | --- |
| Open WebUI | http://127.0.0.1:3000 | primary chat UI |
| API health | http://127.0.0.1:8000/health | `{"status":"ok"}` |
| Admin/debug dashboard | http://127.0.0.1:8000/demo | evaluation + debug only |
| Ollama | http://127.0.0.1:11434/api/tags | runtime model list |

Point Open WebUI's OpenAI connection at `http://api:8000/v1` (inside the compose network) and
import the platform tool (see [Open WebUI integration](#open-webui-integration)).

## Configuration

Runtime selection is provider-agnostic (`.env.example` documents every knob):

```bash
LLM_RUNTIME_PROVIDER=ollama                  # ollama | openai_compat
LLM_BASE_URL=http://ollama:11434             # runtime base URL
LLM_CHAT_MODEL=llama3.2                       # must be pulled/available in the runtime
LLM_EMBED_MODEL=nomic-embed-text
API_DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/industrial_ai
```

**Optional native runtimes** (advanced, not the default path): set
`LLM_RUNTIME_PROVIDER=openai_compat` and `LLM_BASE_URL` to LM Studio
(`http://host.docker.internal:1234/v1`), a native Ollama, or any OpenAI-compatible server. The
deprecated `LMSTUDIO_*` variables still map onto the new `LLM_*` ones for one release.

## The headline flow: Graph RAG + evaluation

```bash
# 1. Create a collection and add a document
COLLECTION=$(curl -s -X POST http://127.0.0.1:8000/rag-collections \
  -H 'Content-Type: application/json' -d '{"name":"Maintenance handbook"}' | jq -r .id)

curl -s -X POST "http://127.0.0.1:8000/rag-collections/$COLLECTION/documents/text" \
  -H 'Content-Type: application/json' \
  -d '{"filename":"notes.md","content":"Pump P-101 feeds reactor R-200. ..."}'

# 2. Build the knowledge graph (worker job: chunk → embed → extract → communities → summarize)
curl -s -X POST "http://127.0.0.1:8000/rag-collections/$COLLECTION/index"

# 3. Query with graph-grounded retrieval (returns answer + evidence trace)
curl -s -X POST "http://127.0.0.1:8000/rag-collections/$COLLECTION/query" \
  -H 'Content-Type: application/json' \
  -d '{"query":"What does pump P-101 feed?","mode":"local"}'

# 4. Generate a reviewable evaluation testset from the collection
curl -s -X POST http://127.0.0.1:8000/evaluation-sets/from-collection \
  -H 'Content-Type: application/json' \
  -d "{\"collection_id\":\"$COLLECTION\",\"name\":\"Maintenance eval\",\"questions_per_chunk\":2}"

# 5. Run an evaluation and fetch the report (groundedness, source coverage, graph stats)
RUN=$(curl -s -X POST http://127.0.0.1:8000/evaluation-runs \
  -H 'Content-Type: application/json' -d '{"evaluation_set_id":"<id>"}' | jq -r .id)
curl -s http://127.0.0.1:8000/evaluation-runs/$RUN/report | jq
```

## Graph RAG

We implement a lean in-repo GraphRAG (not Microsoft's `graphrag` package — its
`pandas`/`graspologic`/`numba` deps have uncertain Python-3.14 wheels and a rigid pipeline):

- **Storage:** Postgres property-graph tables (`rag_chunks`, `rag_entities`, `rag_relationships`,
  `rag_entity_chunks`, `rag_communities` + members, `rag_query_traces`). Embeddings as JSON,
  cosine in pure Python at demo scale; `pgvector` is an optional advanced toggle.
- **Graph algorithms:** `networkx` (pure Python) — `greedy_modularity_communities` for community
  detection.
- **Indexing** (worker job): `parse → chunk → embed_chunks → extract_graph → detect_communities
  → summarize_communities`.
- **Retrieval:** *local* (seed entities/chunks → 1–2 hop expansion → connected chunks +
  relationships + community summaries), *global* (map-reduce over community summaries), and a
  *naive* chunk-vector fallback for answers before the graph is built.

## Open WebUI integration

Run Open WebUI (bundled in compose) and:

- point its OpenAI base URL at `http://api:8000/v1` (compose) or `http://127.0.0.1:8000/v1`
  (native);
- import the platform tool: `GET /openwebui/platform_tools.py`;
- `GET /openwebui/manifest.json` lists the exposed methods: `list_collections`,
  `create_collection`, `upload_text_document`, `search_collection`, `get_entity`, `get_subgraph`,
  `generate_evaluation_set`, `run_rag_evaluation`, `get_evaluation_report`, `get_job_status`.

## Development (AgentDocker) & verification

Development happens inside **AgentDocker** (no host Docker socket, no Docker-in-Docker). Two
verification classes:

**AgentDocker-safe (runs in-container):**

```bash
uv run pyright -p pyrightconfig.json                       # type check
uv run --project apps/api pytest -q apps/api/tests         # unit tests (sqlite + faked runtime)
uv run --project apps/api pytest -q apps/api/tests/test_runtime.py        # one file
bash -n scripts/*.sh && python -m py_compile scripts/*.py  # script syntax
```

**Host runtime (you run on macOS + Docker Desktop — not claimed as passing unless actually run):**

```bash
docker compose config            # validate compose
docker compose up -d --build
docker compose ps
curl -f http://127.0.0.1:8000/health
curl -f http://127.0.0.1:3000
curl -f http://127.0.0.1:11434/api/tags
./scripts/e2e_run_all.sh
```

## Repo layout

```text
.
├─ compose.yml                  # postgres + ollama + open-webui + api + worker
├─ apps/api/
│  ├─ Dockerfile                # python:3.12-slim image for api + worker
│  ├─ alembic/versions/         # date-prefixed migrations
│  ├─ src/api/
│  │  ├─ worker.py              # worker-container entrypoint (dispatcher loop)
│  │  ├─ routers/               # rag, evaluation, models, openai_compat, openwebui, demo, jobs, health
│  │  ├─ services/
│  │  │  ├─ runtime/            # ChatRuntime/EmbeddingRuntime: ollama + openai-compatible
│  │  │  ├─ rag/                # graph_index, graph_retrieval, collections
│  │  │  └─ evaluation/         # qa generation + evaluation runs/reports
│  │  └─ static/
│  │     ├─ demo/               # admin/evaluation/debug dashboard (NOT a chat UI)
│  │     └─ openwebui/          # importable Open WebUI tool
│  └─ tests/
├─ scripts/                     # e2e smoke entrypoints
├─ docs/                        # architecture, ADRs, migration plan
└─ data/                        # sample docs, collection storage
```

## Limitations

- No auth / multi-user.
- Graph build is LLM-heavy; on small Ollama models extraction quality varies — use the naive
  fallback mode for answers before the graph finishes, and a larger extraction model for quality.
- Full Docker runtime validation is host-side by default; AgentDocker performs static + unit
  checks only.
- `markitdown` for richer document parsing is deferred until Python 3.14 `onnxruntime` wheels
  exist; PDF extraction stays on `pypdf`.

## Versioning

- **Unreleased (2026-06)** — Docker-first Open WebUI redirect: restore compose
  (postgres/ollama/open-webui/api/worker), runtime adapter (Ollama default, OpenAI-compatible
  optional), **fine-tuning removed**, **Graph RAG** index lifecycle, evaluation testset
  generation + evaluation runs/reports. See `docs/open-webui-docker-migration.md`.
- **v0.9.0 / v0.8.0** — prior Mac-native MLX QLoRA + LM Studio shape (superseded). See
  `CHANGELOG.md`.
