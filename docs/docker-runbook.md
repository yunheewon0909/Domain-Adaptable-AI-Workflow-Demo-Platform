# Docker runbook (host-side)

These commands run on the **macOS host** with Docker Desktop — not inside AgentDocker, where the
Docker daemon is unavailable by design (ADR 0011). Each step lists its expected success signal.

## 1. Configure and start

```bash
cp .env.example .env            # defaults already target the Ollama container
docker compose config           # validates compose; prints the merged config
docker compose up -d --build
docker compose ps               # all services "running"/"healthy"
```

Expected: `postgres` and `api` report `healthy`; `ollama`, `worker`, `open-webui` report `running`.

## 2. Pull runtime models (one time)

```bash
docker compose exec ollama ollama pull llama3.2          # chat (LLM_CHAT_MODEL)
docker compose exec ollama ollama pull nomic-embed-text  # embeddings (LLM_EMBED_MODEL)
docker compose exec ollama ollama list                   # both models listed
```

## 3. Health checks

```bash
curl -fsS http://127.0.0.1:8000/health        # {"status":"ok"}
curl -fsS http://127.0.0.1:8000/v1/models     # JSON model list from the runtime
curl -fsS http://127.0.0.1:11434/api/tags     # Ollama tags include the pulled models
curl -fsS http://127.0.0.1:3000 >/dev/null && echo "open-webui up"   # HTTP 200
```

## 4. Open WebUI

Open http://127.0.0.1:3000, confirm the OpenAI connection points at `http://api:8000/v1`, and
import the platform tool from `http://127.0.0.1:8000/openwebui/platform_tools.py`.

## 5. End-to-end smoke

```bash
./scripts/e2e_run_all.sh         # added in Phase 9; exercises rag/eval/openwebui surfaces
```

## Logs / teardown

```bash
docker compose logs --tail=200 api worker ollama open-webui
docker compose down              # add -v to also drop volumes (postgres/ollama/openwebui/app data)
```
