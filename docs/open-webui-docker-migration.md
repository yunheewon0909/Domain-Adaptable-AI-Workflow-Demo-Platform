# Migration: Mac-native fine-tuning → Docker-first Open WebUI Graph RAG / evaluation platform

Status: **in progress** (2026-06). This document records the target architecture and the
phased migration. It supersedes the MLX QLoRA / LM Studio framing in
`docs/mac-native-transition-plan.md`.

## Why

The previous product was a Mac-native FastAPI monolith whose headline was **MLX QLoRA
fine-tuning served through LM Studio**. We are redirecting to a **Docker-first domain RAG +
evaluation backend** that plugs into **Open WebUI** as the primary chat UI. Fine-tuning is
removed from the core product. The bar is: **a basic user runs `docker compose up` and
everything works** — no Homebrew, no MLX, no LM Studio. Native runtimes remain available only
as optional configuration.

## Target architecture

| Concern | Target |
| --- | --- |
| Primary UI | **Open WebUI** (container) |
| Default runtime | **Ollama** (container) for chat + embeddings |
| Backend | FastAPI domain **RAG / evaluation / report** API (container) |
| Worker | Separate **worker** container for long-running index/eval jobs |
| Database | **Postgres** (container) |
| Optional runtimes | LM Studio, native Ollama, any OpenAI-compatible endpoint — config only |
| Fine-tuning | **Removed** from core |
| Q/A generation | Kept, **repurposed as evaluation/testset generation** |
| `/demo` | Admin / evaluation / debug dashboard only — **never** a competing chat UI |

## Core capability: Graph RAG

RAG is the core. We implement a **lean in-repo GraphRAG** — not Microsoft's `graphrag` PyPI
package (heavy `pandas`/`graspologic`/`numba` deps with uncertain Python-3.14 wheels and a
file-based pipeline).

- **Storage:** Postgres property-graph tables — `rag_chunks`, `rag_entities`,
  `rag_relationships`, `rag_entity_chunks`, `rag_communities` (+ members), and
  `rag_query_traces` for evaluation evidence. Embeddings stored as JSON; cosine in pure Python
  at demo scale. `pgvector` is an optional advanced toggle, not the default.
- **Graph algorithms:** `networkx` (pure Python, no native deps) —
  `greedy_modularity_communities` for community detection (no Leiden/graspologic needed).
- **LLM extraction + embeddings:** the runtime adapter (Ollama by default).
- **Indexing** (worker jobs, reusing the existing jobs table + dispatcher):
  `parse → chunk → embed_chunks → extract_graph → detect_communities → summarize_communities`.
- **Retrieval:** *local search* (query → seed chunks/entities → 1–2 hop graph expansion →
  connected chunks + relationships + community summaries → traced context); *global search*
  (map-reduce over community summaries); *naive fallback* (plain chunk-vector retrieval before
  the graph is built).

The stored retrieval traces power the evaluation phases (groundedness + source coverage scored
against real evidence), which is what differentiates this from plain Open WebUI RAG chat.

## Runtime adapter

`apps/api/src/api/services/runtime/` defines `ChatRuntime` + `EmbeddingRuntime` protocols with
an `OpenAICompatRuntime` base (covers Ollama `/v1/*`, LM Studio, any OpenAI-compatible
endpoint) and an `OllamaRuntime` subclass (native `/api/tags`, `/api/embed`). Selected by
`LLM_RUNTIME_PROVIDER` (default `ollama`), `LLM_BASE_URL` (default `http://ollama:11434`),
`LLM_CHAT_MODEL`, `LLM_EMBED_MODEL`. The old `LMSTUDIO_*` envs survive one release as
deprecated aliases. LM Studio is never required.

## Development & verification model (AgentDocker)

Development happens inside **AgentDocker** (no host bind mounts, no host Docker socket, no
Docker-in-Docker). Two verification classes:

- **AgentDocker-safe (run in-container):** repo inspection, `git` status/diff, unit tests
  (sqlite + faked runtime), `rg` greps, `bash -n` / `python -m py_compile`, compose
  service-name structure checks. PyYAML is not installed, so compose is structure-checked with
  `rg`, not parsed.
- **Host runtime (the user runs on macOS + Docker Desktop):** `docker compose up`, service
  health on :8000/:3000/:11434/:5432, browser + Open WebUI tool import, model pull + inference
  against the Ollama container, full E2E scripts.

We never claim host runtime validation passed unless it actually ran; instead we emit exact
host commands and expected success signals.

## Phases

| # | Phase | Conventional commit |
| --- | --- | --- |
| 0 | Migration plan doc (this file) | `docs(architecture): outline open-webui-first docker migration` |
| 1 | Reframe README/CHANGELOG/CLAUDE.md + ADRs | `docs(architecture): reframe project as docker-first open-webui backend` |
| 2 | Restore `compose.yml` (postgres/ollama/open-webui/api/worker) + Dockerfile | `feat(docker): restore open-webui ollama postgres api worker compose` |
| 3 | Runtime adapter (Ollama + OpenAI-compatible) | `feat(runtime): add configurable ollama and openai-compatible adapters` |
| 4 | Remove fine-tuning (code + tables) | `refactor(product): remove fine-tuning from core workflow` |
| 5 | Graph RAG index lifecycle | `feat(rag): add graph rag indexing, communities, and traced retrieval` |
| 6 | Evaluation-set generation | `feat(evaluation): generate reviewable qa testsets from rag chunks` |
| 7 | RAG evaluation runs + reports | `feat(evaluation): add rag evaluation runs and reports` |
| 8 | Open WebUI tool integration | `feat(openwebui): expose domain graph-rag evaluation tools` |
| 9 | Rebuild E2E for the new product | `test(e2e): add docker-first openwebui runtime validation` |

Each phase: implement → AgentDocker-safe checks → conventional commit on `main`.
