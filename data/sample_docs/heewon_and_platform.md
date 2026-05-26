# Heewon and the Domain-Adaptable AI Workflow Demo Platform

## About Heewon

Heewon is a software developer who builds practical AI infrastructure tools. He communicates through Discord in the AgentOS server, where his primary channel is `#Domain-Adaptable-AI-Workflow-Demo-Platform`. He prefers a detailed and formal communication style — responses should be thorough, structured, and use proper formal address. He dislikes casual or terse replies.

Heewon requires two information-quality standards in every interaction: (1) Always provide the latest, up-to-date information — never present stale or outdated facts. (2) Never assume — verify or state uncertainty explicitly rather than guessing. Sources should only be provided when explicitly asked.

His development philosophy emphasizes minimal complexity and single-branch workflows with direct commits to the `main` branch. He intentionally avoids multi-branch workflows, preferring a streamlined approach where the main branch is the single source of truth. He has deleted feature branches on purpose to maintain this discipline.

Heewon is also responsible for the KASEGYPT project, a static one-page site for a Korean piping and mechanical engineering company called (주)카스이집트. The site is deployed via Cloudflare Pages to https://www.kasegypt.com/. For coding work on that project, Heewon prefers using Claude Code as his coding agent. His development machine is accessible via Tailscale at heewons-macbook-air-1.tail39987e.ts.net.

Heewon's canonical documentation references include the official documentation sites for Homebrew, tmux, Hermes Agent, OpenClaw, OpenCode, Oh My OpenAgent, Claude Code, Codex, Discord, and Tailscale. He always consults official docs first before any other source.

## The Domain-Adaptable AI Workflow Demo Platform

### Overview

The Domain-Adaptable AI Workflow Demo Platform is a macOS-native FastAPI monolith designed to make AI fine-tuning accessible. It integrates MLX QLoRA fine-tuning with reviewer-curated RAG (Retrieval-Augmented Generation) into a single, self-contained application. The platform targets Mac users who want to fine-tune language models on their own domain-specific documents without needing cloud infrastructure or complex distributed systems.

### Core Loop: The 3-Step Wizard

The platform's headline workflow is a 3-step wizard accessible through the `/demo` web interface:

1. **Knowledge Base (RAG Collection):** Users upload documents (TXT, MD, and PDF formats) into a RAG collection. The platform stores document content and metadata, making it searchable through embedding-based retrieval.

2. **Train (Optional):** Users can generate Q/A pairs from the RAG collection using LM Studio, then fine-tune a language model with MLX QLoRA on their Mac's GPU via Metal acceleration. The platform shells out to brew-installed `mlx_lm.lora` and `mlx_lm.fuse` CLIs for training and model fusion.

3. **Chat:** Users can chat with their fine-tuned model through an embedded chat panel with model picker, RAG grounding toggle, and source surfacing. Power users can also connect external chat clients like lobe-chat or Open WebUI.

### Technical Architecture

The platform runs as a single FastAPI application under Python 3.14 with no Docker, no separate worker processes, and no cloud dependencies. PostgreSQL runs locally via `brew services start postgresql@16`. LM Studio serves chat and embedding models at `http://127.0.0.1:1234/v1`.

Key architectural components include:

- **PostgreSQL** is the system of record for the queue, dataset rows, training jobs, model registry, and RAG collection metadata. RAG document content is stored both as `text_preview` in the database and as original files on disk under `data/rag_collections/`.

- **The jobs table** serves as the queue and lifecycle source of truth, with rows transitioning through states: `queued → running → succeeded/failed`. Fine-tuning jobs have a richer phase model: `queued → preparing_data → training → packaging → registering → succeeded/failed`.

- **An async background dispatcher** polls the jobs table, claims `queued` rows using `SELECT ... FOR UPDATE SKIP LOCKED`, and dispatches runner modules in-process. Long-running MLX subprocesses stream their stdout/stderr directly to `data/model_artifacts/<job_id>/trainer_output/training.log`.

- **The OpenAI-compatible shim** at `/v1/chat/completions` proxies requests to LM Studio with real SSE streaming support. The `/v1/models` endpoint lists only readiness-gated models (those where LM Studio has confirmed the model is loaded).

- **Readiness gating** ensures only fully published models appear as selectable. Models progress through states: `artifact_ready` (adapter validated) → `publish_ready` (fused model placed in LM Studio) → `published/selectable` (LM Studio confirms the model is loaded).

### Fine-Tuning Pipeline

The fine-tuning pipeline is the platform's core differentiator:

1. **Dataset Creation:** Users create a dataset version from a RAG collection. The Q/A generator chunks documents, sends each chunk to LM Studio with a prompt asking for strict-JSON `{"question": "...", "answer": "..."}` pairs, deduplicates near-identical questions across chunks, and filters out malformed pairs (minimum question length 8 characters, minimum answer length 4 characters).

2. **Dataset Versioning:** Datasets are versioned. Users can inspect rows, lock a version (preventing further modification), and then enqueue training. Locking ensures reproducibility — the exact dataset used for training is permanently preserved.

3. **MLX QLoRA Training:** The trainer resolves the base model from LM Studio's local model cache (using the model the user selected in LM Studio's UI, not a separate download), exports the dataset as JSONL files, and runs `mlx_lm.lora` for QLoRA adapter training followed by `mlx_lm.fuse` to merge the adapter weights into a single fused model. Training uses Metal GPU acceleration on Apple Silicon Macs.

4. **Publishing:** After training, the publish flow symlinks the fused model into `~/.lmstudio/models/demo/<job_id>/` and probes LM Studio's `/v1/models` endpoint. Once LM Studio reports the model as loaded, the registry row flips to selectable and the model appears in the platform's model picker and API.

### RAG (Retrieval-Augmented Generation)

The RAG system is collection-managed. Each collection contains documents, and each document has a `text_preview` extracted from the uploaded file. PDF text extraction uses `pypdf`. Embeddings are computed by LM Studio using the configured embedding model. The RAG retrieval can be used to ground chat completions by passing `rag_collection_id` and `top_k` parameters to the chat API.

### Demo UI

The `/demo` interface is a single-screen 3-step wizard built with vanilla JavaScript and Tailwind CSS via CDN (no build step). It supports automatic dark/light mode via `prefers-color-scheme`. The wizard guides users through Knowledge Base → Train → Chat with inline plain-language explainers at each step. The embedded chat panel includes a model picker, RAG grounding toggle, and source document surfacing.

### Runtime Requirements

- Python 3.14
- PostgreSQL 16 (via Homebrew)
- LM Studio (local installation)
- brew-installed `mlx-lm` for training
- `uv` for package management
- Apple Silicon Mac (M1/M2/M3/M4) for Metal GPU acceleration

### Configuration

The platform is configured through environment variables including:
- `LMSTUDIO_CHAT_MODEL` — the chat model loaded in LM Studio (e.g., `qwen3.5-4b-mlx`)
- `LMSTUDIO_EMBED_MODEL` — the embedding model (e.g., `text-embedding-nomic-embed-text-v1.5`)
- `API_DATABASE_URL` — PostgreSQL connection string
- `MODEL_ARTIFACT_DIR` — where training artifacts are stored
- `FT_TRAINER_BACKEND` — the training backend (`mlx_qlora` for real training)

### Heewon's Role

Heewon is the creator and sole developer of the Domain-Adaptable AI Workflow Demo Platform. He maintains the repository at `/Volumes/Samsung/Domain-Adaptable-AI-Workflow-Demo-Platform` and follows a strict single-branch (main only) development workflow. He has been iteratively refining the platform through multiple versions — removing unnecessary domain slices (PLC test automation, legacy workflow system), simplifying the UI from a multi-tab admin console to a focused 3-step wizard, and migrating from Ollama to LM Studio as the exclusive serving runtime.

His development style is characterized by aggressive simplification — removing entire domain slices, worker processes, Docker Compose files, and Ollama dependencies when they no longer serve the core vision. He prefers a narrow, focused codebase over a sprawling platform.
