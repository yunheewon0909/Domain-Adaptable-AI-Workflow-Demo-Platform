#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"

print_step() {
  printf '[step] %s\n' "$1"
}

print_ok() {
  printf '[ok] %s\n' "$1"
}

print_fail() {
  printf '[fail] %s\n' "$1" >&2
}

require_200() {
  local path="$1"
  local url="${API_BASE_URL}${path}"
  local status
  status="$(curl -sS -o /tmp/e2e-response.$$ -w '%{http_code}' "$url")"
  if [[ "$status" != "200" ]]; then
    print_fail "GET ${path} returned ${status}: $(cat /tmp/e2e-response.$$)"
    rm -f /tmp/e2e-response.$$
    exit 1
  fi
  rm -f /tmp/e2e-response.$$
  print_ok "GET ${path} returned 200"
}

wait_for_health() {
  local deadline=$((SECONDS + 90))
  while (( SECONDS < deadline )); do
    if curl -fsS "${API_BASE_URL}/health" >/dev/null 2>&1; then
      print_ok 'API health returned 200'
      return 0
    fi
    sleep 2
  done
  print_fail 'Timed out waiting for /health'
  exit 1
}

check_service_running() {
  local service="$1"
  local status
  status="$(docker compose -f "$ROOT_DIR/compose.yml" ps --format json "$service" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data[0].get("State","")) if data else print("")')"
  if [[ -z "$status" ]]; then
    print_fail "Service ${service} was not found in docker compose ps"
    exit 1
  fi
  case "$status" in
    running|healthy)
      print_ok "Service ${service} is ${status}"
      ;;
    *)
      print_fail "Service ${service} is ${status}"
      exit 1
      ;;
  esac
}

print_step 'Ensuring ollama-models volume exists'
docker volume create ollama-models >/dev/null 2>&1 || true

print_step 'Starting docker compose stack'
docker compose -f "$ROOT_DIR/compose.yml" up -d --build

print_step 'Inspecting compose service states'
docker compose -f "$ROOT_DIR/compose.yml" ps
check_service_running postgres
check_service_running api
check_service_running worker
check_service_running ollama

wait_for_health
require_200 /demo
require_200 /models
require_200 /workflows
require_200 /rag-collections
require_200 /plc-targets

print_step 'Checking api/worker logs for startup fatals'
python3 - "$ROOT_DIR" <<'PY'
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
fatal_tokens = [
    "application startup failed",
    "traceback (most recent call last)",
    "modulenotfounderror:",
    "importerror:",
    "alembic.util.exc.commanderror",
]
allowed_context = [
    "rag index is not ready",
]

for service in ("api", "worker"):
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(root / "compose.yml"),
            "logs",
            "--no-color",
            "--tail=200",
            service,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    text = result.stdout.lower()
    for token in fatal_tokens:
        if token in text and not any(context in text for context in allowed_context):
            print(f"[fail] Found fatal startup token in {service} logs: {token}")
            raise SystemExit(1)
    print(f"[ok] No obvious fatal startup token found in {service} logs")
PY

print_ok 'Docker full-stack smoke passed'
