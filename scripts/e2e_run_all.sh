#!/usr/bin/env bash
# Run the Docker-first E2E smoke suite against a running stack.
#
# Host-side: start the stack first —
#   cp .env.example .env && docker compose up -d --build
#   docker compose exec ollama ollama pull llama3.2
#   docker compose exec ollama ollama pull nomic-embed-text
# then: ./scripts/e2e_run_all.sh
#
# Override targets with API_BASE_URL / OPENWEBUI_URL / OLLAMA_URL.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

run_step() {
  local label="$1"
  shift
  printf '[step] %s\n' "$label"
  "$@"
  printf '[ok] %s\n' "$label"
}

# Run scripts from the scripts dir so `import e2e_helpers` resolves.
cd "$ROOT_DIR/scripts"
PY="uv run --project $ROOT_DIR/apps/api python"

run_step "compose smoke" bash "$ROOT_DIR/scripts/e2e_compose_smoke.sh"
run_step "runtime smoke" $PY e2e_runtime_smoke.py
run_step "rag index smoke" $PY e2e_rag_index_smoke.py
run_step "evaluation set smoke" $PY e2e_evaluation_set_smoke.py
run_step "rag evaluation report smoke" $PY e2e_rag_evaluation_report_smoke.py
run_step "open webui tools smoke" $PY e2e_openwebui_tools_smoke.py

printf '[ok] All Docker-first E2E scripts completed\n'
