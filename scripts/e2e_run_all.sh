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

run_step "Docker stack smoke" "$ROOT_DIR/scripts/e2e_docker_stack_smoke.sh"
run_step "Ollama inference smoke" python "$ROOT_DIR/scripts/e2e_ollama_inference_smoke.py"
run_step "Workflow real-model smoke" python "$ROOT_DIR/scripts/e2e_workflow_real_model_smoke.py"
run_step "RAG collection workflow smoke" python "$ROOT_DIR/scripts/e2e_rag_collection_workflow_smoke.py"
run_step "FT smoke fallback" python "$ROOT_DIR/scripts/e2e_ft_smoke_fallback.py"
run_step "Model gating smoke" python "$ROOT_DIR/scripts/e2e_model_gating_smoke.py"
run_step "RAG document management" python "$ROOT_DIR/scripts/e2e_rag_document_management.py"
run_step "PLC stub pipeline" python "$ROOT_DIR/scripts/e2e_plc_stub_pipeline.py"

printf '[ok] All configured E2E scripts completed\n'
