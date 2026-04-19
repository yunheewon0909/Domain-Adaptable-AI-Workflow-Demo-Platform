#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

worker_runtime="auto"
args=()
while (($#)); do
  case "$1" in
    --worker-runtime)
      if (($# < 2)); then
        printf 'ft_smoke_preflight.sh: missing value for --worker-runtime\n' >&2
        exit 2
      fi
      worker_runtime="$2"
      args+=("$1" "$2")
      shift 2
      ;;
    --worker-runtime=*)
      worker_runtime="${1#*=}"
      args+=("$1")
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

run_host_preflight() {
  uv run --project "$REPO_ROOT/apps/api" python "$REPO_ROOT/apps/api/src/api/services/fine_tuning/preflight.py" "${args[@]}"
}

run_docker_preflight() {
  local api_base_url="${API_BASE_URL:-http://api:8000}"
  docker compose -f "$REPO_ROOT/compose.yml" exec -T \
    -e API_BASE_URL="$api_base_url" \
    worker \
    sh -lc 'cd /workspace && uv run --project apps/api python apps/api/src/api/services/fine_tuning/preflight.py "$@"' -- "${args[@]}"
}

if [[ "$worker_runtime" == "docker" ]]; then
  run_docker_preflight
else
  run_host_preflight
fi
