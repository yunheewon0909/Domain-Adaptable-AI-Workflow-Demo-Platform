#!/usr/bin/env bash
# Host-side compose smoke test: verifies the five services answer on their ports.
# Run on the macOS host after `docker compose up -d --build`.
#   ./scripts/e2e_compose_smoke.sh
set -euo pipefail

API_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
OPENWEBUI_URL="${OPENWEBUI_URL:-http://127.0.0.1:3000}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"

check() {
  local label="$1" url="$2"
  printf '[step] %s (%s)\n' "$label" "$url"
  if curl -fsS "$url" >/dev/null 2>&1; then
    printf '[ok] %s reachable\n' "$label"
  else
    printf '[fail] %s NOT reachable at %s\n' "$label" "$url"
    return 1
  fi
}

check "API health" "$API_URL/health"
check "API /v1/models" "$API_URL/v1/models"
check "Open WebUI" "$OPENWEBUI_URL"
check "Ollama tags" "$OLLAMA_URL/api/tags"

printf '[ok] compose smoke passed\n'
