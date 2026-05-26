# Heewon and the Domain-Adaptable AI Workflow Demo Platform

## Who Is Heewon?

Heewon is a software developer who builds practical AI infrastructure tools. He works primarily on macOS and communicates through Discord in the AgentOS server, where his primary channel is the Domain-Adaptable-AI-Workflow-Demo-Platform channel. His development machine is an Apple Silicon Mac accessible via Tailscale at heewons-macbook-air-1.tail39987e.ts.net.

Heewon requires two information-quality standards in every interaction: (1) Always provide the latest, up-to-date information — never present stale or outdated facts. (2) Never assume — verify or state uncertainty explicitly rather than guessing. Sources should only be provided when explicitly asked.

His communication style is detailed and formal. He prefers thorough, structured responses with proper formal address. He dislikes casual or terse replies.

Heewon's canonical documentation references include the official documentation sites for Homebrew, tmux, Hermes Agent, OpenClaw, OpenCode, Oh My OpenAgent, Claude Code, Codex, Discord, and Tailscale. He always consults official docs first before any other source when researching or citing any tool.

Heewon is also the developer of the KASEGYPT project, a static one-page site for a Korean piping and mechanical engineering company called (주)카스이집트. The site is deployed via Cloudflare Pages to https://www.kasegypt.com/. For coding work on the KASEGYPT project, Heewon prefers using Claude Code as his coding agent. The KASEGYPT repository is located at /Volumes/Samsung/kasegypt-site and deploys through a workflow of editing, inspecting via Tailscale preview, committing to git, and producing a zip file at /Volumes/Samsung/kasegypt-site-upload.zip for Cloudflare Pages upload.

## Heewon's Development Philosophy

Heewon's development philosophy emphasizes minimal complexity and single-branch workflows with direct commits to the main branch. He intentionally avoids multi-branch workflows, preferring a streamlined approach where the main branch is the single source of truth. He has explicitly deleted feature branches on purpose to maintain this discipline.

His development style is characterized by aggressive simplification — removing entire domain slices, worker processes, Docker Compose files, and legacy dependencies when they no longer serve the core vision. He prefers a narrow, focused codebase over a sprawling platform. The Domain-Adaptable AI Workflow Demo Platform repository shrank from carrying three parallel domains (legacy reviewer workflow, PLC test automation, and AI ops fine-tuning) down to a single focused concern: MLX QLoRA fine-tuning plus collection-managed RAG. This removed approximately 14,631 lines of code while adding only 1,674 lines, for a net reduction of over 12,000 lines.

## What Is the Domain-Adaptable AI Workflow Demo Platform?

The Domain-Adaptable AI Workflow Demo Platform is a macOS-native FastAPI monolith designed to make AI fine-tuning accessible to Mac users. It integrates MLX QLoRA fine-tuning with reviewer-curated RAG (Retrieval-Augmented Generation) into a single, self-contained application. Users can upload their own documents, generate question-answer pairs from them, fine-tune a language model on those pairs using Apple Silicon GPU acceleration, and chat with the resulting model — all without cloud infrastructure or complex distributed systems.

The platform targets Mac users who want to customize language models for domain-specific knowledge. It is built entirely for Apple Silicon (M1/M2/M3/M4) Macs with Metal GPU acceleration and runs on Python 3.14.

## The 3-Step Wizard

The platform's headline workflow is a 3-step wizard accessible through the /demo web interface:

1. Knowledge Base (RAG Collection): Users upload documents in TXT, MD, and PDF formats into a RAG collection. The platform stores document content as both text_preview metadata in PostgreSQL and as original files on disk under data/rag_collections/. PDF text extraction uses the pypdf library.

2. Train (Optional): Users generate Q/A pairs from the RAG collection using LM Studio, then fine-tune a language model with MLX QLoRA on their Mac's GPU via Metal acceleration. The generator chunks documents into segments of about 1500 characters, sends each chunk to LM Studio with a prompt asking for strict-JSON question-answer pairs, deduplicates near-identical questions across chunks, and filters out malformed pairs where questions are shorter than 8 characters or answers shorter than 4 characters.

3. Chat: Users chat with their fine-tuned model through an embedded chat panel that includes a model picker dropdown, a RAG grounding toggle, and source document surfacing. Power users can also connect external chat clients like lobe-chat or Open WebUI by pointing them at the platform's OpenAI-compatible API endpoint at /v1/chat/completions.

## Technical Architecture

The platform runs as a single FastAPI application with no Docker containers, no separate worker processes, and no cloud dependencies. PostgreSQL 16 runs locally via Homebrew services. LM Studio serves chat and embedding models at http://127.0.0.1:1234/v1.

Key architectural components include:

PostgreSQL is the system of record for the queue, dataset rows, training jobs, model registry, and RAG collection metadata. RAG document content is stored both as text_preview in the database's rag_documents.metadata_json column and as original files on disk under data/rag_collections/.

The jobs table serves as the queue and lifecycle source of truth, with rows transitioning through states: queued, running, succeeded, or failed. Fine-tuning jobs have a richer phase model: queued, preparing_data, training, packaging, registering, and finally succeeded or failed.

An async background dispatcher polls the jobs table, claims queued rows using PostgreSQL's SELECT FOR UPDATE SKIP LOCKED, and dispatches runner modules in-process via asyncio.to_thread(). There is no separate worker process — the dispatcher runs inside the FastAPI lifespan handler. For SQLite backends, the dispatcher falls back to an in-process asyncio.Lock instead of row-level locking.

The OpenAI-compatible shim at /v1/chat/completions proxies requests to LM Studio with real SSE streaming support for token-by-token delivery. The /v1/models endpoint lists only readiness-gated models where LM Studio has confirmed the model is loaded.

The model registry uses readiness gating to ensure only fully published models appear as selectable. Models progress through states: artifact_ready (adapter validated) to publish_ready (fused model placed in LM Studio's models directory) to published/selectable (LM Studio confirms the model is loaded via /v1/models probe).

## API Routers

The platform's API is organized into these routers under apps/api/src/api/routers/:

- fine_tuning: Dataset CRUD, version status transitions, training job enqueue, and the dataset-from-RAG-collection Q/A generator endpoint at POST /ft-datasets/from-rag-collection
- models: Registry inspection, model lineage, artifact and log access, publishing that places the fused model under ~/.lmstudio/models/ and probes LM Studio, and inference runs
- rag: Collection CRUD at /rag-collections, document upload and delete, and retrieval preview
- jobs: Generic queue read endpoints
- openai_compat: /v1/models and /v1/chat/completions with real LM Studio SSE passthrough, readiness-gated to selectable registry rows
- openwebui: Serves the importable Open WebUI tool artifact and manifest
- demo: Static reviewer UI built with vanilla JavaScript and Tailwind CSS via CDN, implementing the 3-step wizard
- health: Health check endpoint

## The Fine-Tuning Pipeline

The fine-tuning pipeline is the platform's core differentiator and works in these phases:

1. Dataset Creation: A user creates a dataset version from a RAG collection by calling POST /ft-datasets/from-rag-collection. The Q/A generator pulls the text_preview from each document in the collection, slices it into chunks of approximately 1500 characters, and sends each chunk to LM Studio with a system prompt instructing it to emit a strict JSON array of question-answer pairs. The generator retries once if the first attempt produces invalid JSON, using a stricter prompt that says "Emit ONLY a JSON array, no prose, no markdown, no code fences." Generated pairs are deduplicated across chunks by normalizing the question text (lowercase, whitespace-collapsed, first 80 characters).

2. Dataset Versioning: Datasets are versioned with a train/val/test split. Users can inspect rows, lock a version (preventing further modification), and then enqueue training. Locking ensures reproducibility — the exact dataset used for training is permanently preserved. The status flow is: draft to validated to locked.

3. MLX QLoRA Training: When a training job is enqueued via POST /ft-training-jobs, the platform resolves the trainer model from LM Studio's local model cache. The resolve_trainer_model_name function first checks for an explicit trainer_model_name in hyperparams, then attempts to find the model on disk via the lms ls command and filesystem scanning, and finally falls back to the FT_TRAINER_MODEL_MAP_JSON environment variable. The dataset is exported as JSONL files under data/model_artifacts/<job_id>/dataset_export/. The trainer then runs the brew-installed mlx_lm.lora CLI with parameters for iterations, learning rate, batch size, LoRA rank, and sequence length. Training uses Metal GPU acceleration on Apple Silicon.

4. Model Fusion: After adapter training completes, the trainer runs mlx_lm.fuse to merge the QLoRA adapter weights into a single fused MLX model directory. The fused model directory contains config.json, model.safetensors, tokenizer.json, tokenizer_config.json, and a chat_template.jinja.

5. Publishing: The publish flow at POST /ft-training-jobs/{id}/publish symlinks the fused model directory into ~/.lmstudio/models/<namespace>/<name>/ where the namespace defaults to "demo". It then probes LM Studio's /v1/models endpoint with a 30-second cache invalidation. If LM Studio reports the model as loaded, the registry row flips from artifact_ready to published/selectable, and the model appears in the platform's model picker and API.

## RAG Architecture

The RAG system is collection-managed. Each collection (rag_collections table) contains documents (rag_documents table). Each document stores its text_preview in metadata_json and the original file bytes on disk. PDF text extraction uses pypdf. The markitdown library from Microsoft (~50k GitHub stars) was deferred because its onnxruntime dependency lacks Python 3.14 wheels as of May 2026.

Embeddings are computed by the LM Studio embedding model configured via LMSTUDIO_EMBED_MODEL. The RAG retrieval can ground chat completions by passing rag_collection_id and top_k parameters to the /v1/chat/completions endpoint. The platform's chat client includes a RAG grounding toggle in the demo UI.

RAG collections and documents can be removed entirely: DELETE /rag-documents/{id} removes a single document, while DELETE /rag-collections/{id} cascades to all documents and on-disk storage.

## The Demo UI

The /demo interface is a single-screen 3-step wizard built with vanilla JavaScript and Tailwind CSS via Play CDN with shadcn-inspired CSS variables. There is no build step. The UI supports automatic dark and light mode via the prefers-color-scheme media query.

The wizard guides users through three steps with inline plain-language explainers at each step:

- Step 1 (Knowledge Base): Users create or select a RAG collection, upload documents, and see a document list with metadata. The UI shows the number of documents and total text content size.

- Step 2 (Train): Users select a RAG collection, configure Q/A generation parameters (pairs per chunk, max chunks), generate a dataset, and enqueue fine-tuning. The UI shows training progress with status indicators.

- Step 3 (Chat): An embedded chat panel with a model picker dropdown listing all selectable models, a RAG grounding toggle that injects RAG context into prompts, and source document surfacing that shows which documents contributed to each answer.

The UI was redesigned in version 0.9.1 from a multi-tab admin console with approximately 50 buttons down to about 10 interactive elements in the wizard. The JavaScript, HTML, and CSS files total 674 lines, an 86% reduction from the previous 4,688 lines.

## Runtime Requirements

- Python 3.14 (specified in .python-version)
- PostgreSQL 16 via Homebrew (brew services start postgresql@16)
- LM Studio (local macOS application serving models at port 1234)
- brew-installed mlx-lm package providing mlx_lm.lora and mlx_lm.fuse CLIs
- uv for Python package management
- Apple Silicon Mac (M1/M2/M3/M4) for Metal GPU acceleration

The database is named industrial_ai and can be created with: createdb industrial_ai

## Configuration

The platform is configured through environment variables:

- API_DATABASE_URL: PostgreSQL connection string (default: postgresql+psycopg://postgres:postgres@localhost:5432/industrial_ai)
- LMSTUDIO_BASE_URL: LM Studio API base URL (default: http://localhost:1234/v1)
- LMSTUDIO_CHAT_MODEL: The chat model loaded in LM Studio (e.g., qwen3.5-4b-mlx)
- LMSTUDIO_EMBED_MODEL: The embedding model (e.g., text-embedding-nomic-embed-text-v1.5)
- LMSTUDIO_TIMEOUT_SECONDS: Timeout for LM Studio API calls (default: 600)
- MODEL_ARTIFACT_DIR: Where training artifacts are stored (default: data/model_artifacts)
- FT_TRAINER_BACKEND: Training backend — mlx_qlora for real training or deterministic_smoke for smoke tests
- FT_MAX_SEQ_LENGTH: Maximum sequence length for training (default: 1024)
- FT_MLX_ITERS: Training iterations (default: 1000)
- FT_DEFAULT_TRAINING_METHOD: Always sft_qlora for real training
- MLX_MODEL_NAMESPACE: Namespace for published models (default: demo)
- ADAPTER_PUBLISH_ENABLED: Whether adapter publishing is enabled (default: false)
- FT_ALLOW_SMOKE_FALLBACK: Whether to fall back to deterministic smoke on HF download failure (default: false)
- FT_TRAINER_MODEL_MAP_JSON: JSON mapping of serving model names to trainer checkpoints

## Development History

The platform has evolved through multiple versions. Version 0.8.0 dropped Docker entirely, removing the compose.yml file and the separate apps/worker/ package. It adopted MLX QLoRA via brew mlx-lm, switched serving from Ollama to LM Studio, and upgraded to Python 3.14. All Ollama clients, settings, and environment variables were removed.

Version 0.9.0 was a major scope reduction. The PLC test-automation slice was removed entirely (8 ORM tables, services, routers, and demo mode). The legacy rag.db workflow source was removed (services for workflows, datasets, retrieval, and legacy RAG modules). The database column model_registry.ollama_model_name was renamed to serving_model_name. The dataset-from-RAG-collection endpoint was added as the headline feature. LM Studio auto-registration was implemented for the publish flow. Real SSE streaming was added to the OpenAI-compatible shim. The in-process background job dispatcher was wired up.

Version 0.9.1 redesigned the /demo UI from a multi-tab admin console to a single-screen 3-step wizard. The embedded chat panel gained a model picker, RAG grounding toggle, and source surfacing. External chat client hints were added for lobe-chat and Open WebUI.

## Heewon's Other Tools and Projects

Beyond the Domain-Adaptable AI Workflow Demo Platform, Heewon uses and maintains several tools:

Hermes Agent is his primary AI assistant platform, running on his macOS machine. It provides Discord integration, computer use capabilities for driving the macOS desktop, persistent memory across sessions, and a skill system for reusable workflows.

Heewon uses Claude Code as his preferred coding agent for the KASEGYPT project. He also references OpenCode and Codex as alternative coding agents. For infrastructure, he uses Tailscale for secure remote access to his development machine.

His development environment runs on an external Samsung drive at /Volumes/Samsung/, which hosts both the Domain-Adaptable-AI-Workflow-Demo-Platform and kasegypt-site repositories.
