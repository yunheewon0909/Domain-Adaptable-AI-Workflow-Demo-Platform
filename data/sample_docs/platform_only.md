# Heewon and the Domain-Adaptable AI Workflow Demo Platform

## Who Is Heewon?

Heewon is a software developer who builds practical AI infrastructure tools. He is the creator and sole developer of the Domain-Adaptable AI Workflow Demo Platform. He works primarily on macOS and communicates through Discord in the AgentOS server, where his primary channel is dedicated to discussing and developing this platform.

Heewon requires two information-quality standards in every interaction: first, always provide the latest up-to-date information and never present stale or outdated facts; second, never assume — verify or state uncertainty explicitly rather than guessing.

Heewon's communication style is detailed and formal. He prefers thorough structured responses with proper formal address and dislikes casual or terse replies.

Heewon's development philosophy emphasizes minimal complexity and single-branch workflows with direct commits to the main branch. He intentionally avoids multi-branch workflows, preferring a streamlined approach where the main branch is the single source of truth. He has explicitly deleted feature branches on purpose to maintain this discipline. His development style is characterized by aggressive simplification — removing entire domain slices, worker processes, and legacy dependencies when they no longer serve the core vision. He prefers a narrow focused codebase over a sprawling platform.

## What Is the Domain-Adaptable AI Workflow Demo Platform?

The Domain-Adaptable AI Workflow Demo Platform is a macOS-native FastAPI monolith designed to make AI fine-tuning accessible to Mac users. It integrates MLX QLoRA fine-tuning with reviewer-curated RAG, which stands for Retrieval-Augmented Generation, into a single self-contained application. Users can upload their own documents, generate question-answer pairs from them, fine-tune a language model on those pairs using Apple Silicon GPU acceleration via Metal, and chat with the resulting model — all without cloud infrastructure or complex distributed systems.

The platform targets Mac users who want to customize language models for domain-specific knowledge. It is built entirely for Apple Silicon Macs with M1, M2, M3, or M4 processors, using Metal GPU acceleration. The platform runs on Python 3.14.

## The 3-Step Wizard Workflow

The platform's headline workflow is a 3-step wizard accessible through the /demo web interface:

Step 1 is Knowledge Base, also called the RAG Collection step. Users upload documents in TXT, MD, and PDF formats into a RAG collection. The platform stores document content as both text_preview metadata in PostgreSQL and as original files on disk under the data/rag_collections/ directory. PDF text extraction uses the pypdf library. Users can create multiple collections, upload multiple documents per collection, and delete documents or entire collections as needed.

Step 2 is Train, which is optional. Users generate question and answer pairs from the RAG collection using LM Studio, then fine-tune a language model with MLX QLoRA on their Mac's GPU via Metal acceleration. The Q/A generator chunks documents into segments of approximately 1500 characters, sends each chunk to LM Studio with a prompt asking for strict-JSON question-answer pairs, deduplicates near-identical questions across chunks, and filters out malformed pairs where questions are shorter than 8 characters or answers shorter than 4 characters. Users can configure how many pairs per chunk and how many chunks to process.

Step 3 is Chat. Users chat with their fine-tuned model through an embedded chat panel that includes a model picker dropdown listing all selectable models, a RAG grounding toggle that injects RAG context into prompts, and source document surfacing that shows which documents contributed to each answer. Power users can also connect external chat clients by pointing them at the platform's OpenAI-compatible API endpoint.

## Technical Architecture

The platform runs as a single FastAPI application with no Docker containers, no separate worker processes, and no cloud dependencies. PostgreSQL 16 runs locally via Homebrew services using the command "brew services start postgresql@16". LM Studio serves chat and embedding models locally at the address http://127.0.0.1:1234/v1.

The jobs table serves as the queue and lifecycle source of truth. Rows transition through states: queued, running, succeeded, or failed. Fine-tuning jobs have a richer phase model: queued, then preparing_data, then training, then packaging, then registering, and finally succeeded or failed.

An async background dispatcher polls the jobs table, claims queued rows using the PostgreSQL command SELECT FOR UPDATE SKIP LOCKED, and dispatches runner modules in-process. There is no separate worker process — the dispatcher runs inside the FastAPI lifespan handler.

The OpenAI-compatible shim at the endpoint /v1/chat/completions proxies requests to LM Studio with real SSE streaming support for token-by-token delivery. The /v1/models endpoint lists only readiness-gated models where LM Studio has confirmed the model is loaded.

The model registry uses readiness gating to ensure only fully published models appear as selectable. Models progress through states: artifact_ready means the adapter has been validated, publish_ready means the fused model has been placed in LM Studio's models directory, and published or selectable means LM Studio confirms the model is loaded via a /v1/models probe.

## API Routers

The platform's API is organized into several routers:

The fine_tuning router handles dataset CRUD operations, version status transitions, training job enqueue, and the dataset-from-RAG-collection Q/A generator endpoint at POST /ft-datasets/from-rag-collection.

The models router handles registry inspection, model lineage tracking, artifact and log access, publishing that places the fused model under the .lmstudio/models/ directory, and inference runs.

The rag router handles collection CRUD at /rag-collections, document upload and delete, and retrieval preview.

The openai_compat router provides /v1/models and /v1/chat/completions with real LM Studio SSE passthrough, readiness-gated to selectable registry rows.

The demo router serves the static reviewer UI built with vanilla JavaScript and Tailwind CSS via CDN, implementing the 3-step wizard with no build step required.

## The Fine-Tuning Pipeline in Detail

The fine-tuning pipeline works through five distinct phases.

Phase 1 is Dataset Creation. A user creates a dataset version from a RAG collection by calling POST /ft-datasets/from-rag-collection. The Q/A generator pulls the text_preview from each document in the collection, slices it into chunks of approximately 1500 characters, and sends each chunk to LM Studio with a system prompt instructing it to emit a strict JSON array of question-answer pairs. The generator retries once if the first attempt produces invalid JSON, using a stricter prompt. Generated pairs are deduplicated across chunks by normalizing the question text to lowercase with whitespace collapsed and comparing the first 80 characters.

Phase 2 is Dataset Versioning. Datasets are versioned with a train, validation, and test split. Users can inspect rows, lock a version to prevent further modification, and then enqueue training. Locking ensures reproducibility because the exact dataset used for training is permanently preserved. The status flow is: draft changes to validated, then changes to locked.

Phase 3 is MLX QLoRA Training. When a training job is enqueued via POST /ft-training-jobs, the platform resolves the trainer model from LM Studio's local model cache. The dataset is exported as JSONL files under the data/model_artifacts/ directory. The trainer then runs the brew-installed mlx_lm.lora command-line tool with parameters for iterations, learning rate, batch size, LoRA rank, and sequence length. Training uses Metal GPU acceleration on Apple Silicon.

Phase 4 is Model Fusion. After adapter training completes, the trainer runs the mlx_lm.fuse command to merge the QLoRA adapter weights into a single fused MLX model directory. The fused model directory contains a config.json file, a model.safetensors file, a tokenizer.json file, a tokenizer_config.json file, and a chat_template.jinja template file.

Phase 5 is Publishing. The publish flow symlinks the fused model directory into the LM Studio models directory under a namespace that defaults to "demo". It then probes LM Studio's /v1/models endpoint. If LM Studio reports the model as loaded, the registry row flips from artifact_ready to published and selectable, and the model appears in the platform's model picker and API.

## RAG Architecture

The RAG system is collection-managed. Each collection lives in the rag_collections database table, and each document lives in the rag_documents table. Each document stores its text_preview in the metadata_json column and the original file bytes on disk. PDF text extraction uses the pypdf library.

Embeddings are computed by the LM Studio embedding model configured via the LMSTUDIO_EMBED_MODEL environment variable. The RAG retrieval can ground chat completions by passing a rag_collection_id and a top_k parameter to the /v1/chat/completions endpoint. The platform's demo UI includes a RAG grounding toggle in the chat panel.

## The Demo User Interface

The /demo interface is a single-screen 3-step wizard built with vanilla JavaScript and Tailwind CSS delivered via Play CDN with shadcn-inspired CSS variables. There is no build step required. The UI supports automatic dark and light mode switching via the prefers-color-scheme CSS media query.

The wizard guides users through three steps with inline plain-language explainers at each step. Step 1 lets users create or select a RAG collection and upload documents. Step 2 lets users select a RAG collection, configure Q/A generation parameters, generate a dataset, and enqueue fine-tuning, with the UI showing training progress. Step 3 provides an embedded chat panel with model picker, RAG grounding toggle, and source document surfacing.

The UI was redesigned in version 0.9.1 of the platform from a multi-tab admin console with approximately 50 buttons down to about 10 interactive elements in the wizard layout. The total JavaScript, HTML, and CSS code is 674 lines.

## Runtime Requirements

The platform requires Python 3.14 as specified in the .python-version file. PostgreSQL 16 must be installed via Homebrew and started with "brew services start postgresql@16". The database is named industrial_ai and is created with the "createdb industrial_ai" command. LM Studio must be installed as a local macOS application serving models at port 1234. The brew package mlx-lm must be installed, providing the mlx_lm.lora and mlx_lm.fuse command-line tools. The uv tool is used for Python package management with the command "uv sync --dev". An Apple Silicon Mac with an M1, M2, M3, or M4 processor is required for Metal GPU acceleration.

## Configuration Environment Variables

The platform is configured through environment variables. API_DATABASE_URL specifies the PostgreSQL connection string. LMSTUDIO_BASE_URL specifies the LM Studio API base URL. LMSTUDIO_CHAT_MODEL specifies which chat model is loaded in LM Studio, such as qwen3.5-4b-mlx. LMSTUDIO_EMBED_MODEL specifies the embedding model, such as text-embedding-nomic-embed-text-v1.5. LMSTUDIO_TIMEOUT_SECONDS sets the timeout for API calls, defaulting to 600 seconds. MODEL_ARTIFACT_DIR specifies where training artifacts are stored. FT_TRAINER_BACKEND specifies the training backend, either mlx_qlora for real training or deterministic_smoke for testing. FT_MAX_SEQ_LENGTH sets the maximum sequence length, defaulting to 1024. FT_MLX_ITERS sets the number of training iterations, defaulting to 1000. MLX_MODEL_NAMESPACE sets the namespace for published models, defaulting to "demo".

## Development History

The platform has evolved through multiple versions. Version 0.8.0 dropped Docker entirely, removing the Docker Compose file and the separate worker package. It adopted MLX QLoRA via the brew-installed mlx-lm package, switched the serving runtime from Ollama to LM Studio, and upgraded to Python 3.14. All Ollama-related clients, settings, and environment variables were removed.

Version 0.9.0 was a major scope reduction. The PLC test-automation domain was removed entirely, including 8 database tables and all related services and routers. The legacy workflow source was removed. The database column was renamed from ollama_model_name to serving_model_name. The dataset-from-RAG-collection endpoint was added as the headline feature. LM Studio auto-registration was implemented for the publish flow. Real SSE streaming was added to the OpenAI-compatible API shim.

Version 0.9.1 redesigned the demo interface from a multi-tab admin console into a single-screen 3-step wizard. The embedded chat panel gained a model picker, RAG grounding toggle, and source document surfacing feature.

The platform repository shrank from carrying three parallel domains down to a single focused concern: MLX QLoRA fine-tuning plus collection-managed RAG. This removed approximately 14,631 lines of code while adding only 1,674 lines, for a net reduction of over 12,000 lines.
