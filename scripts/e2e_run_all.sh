#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

run_step() {
  local label="$1"
  shift
  printf '[step] %s\n' "$label"
  "$@"
  printf '[ok] %s\n' "$label"
}

PY="uv run --project $ROOT_DIR/apps/api python"

run_step "QLoRA-on-RAG dataset smoke" $PY "$ROOT_DIR/scripts/e2e_qlora_rag_dataset_smoke.py"
run_step "FT smoke fallback" $PY "$ROOT_DIR/scripts/e2e_ft_smoke_fallback.py"
run_step "RAG document management" $PY "$ROOT_DIR/scripts/e2e_rag_document_management.py"

printf '[ok] All configured E2E scripts completed\n'
