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

run_step "QLoRA-on-RAG dataset smoke" python "$ROOT_DIR/scripts/e2e_qlora_rag_dataset_smoke.py"
run_step "Workflow real-model smoke" python "$ROOT_DIR/scripts/e2e_workflow_real_model_smoke.py"
run_step "RAG collection workflow smoke" python "$ROOT_DIR/scripts/e2e_rag_collection_workflow_smoke.py"
run_step "FT smoke fallback" python "$ROOT_DIR/scripts/e2e_ft_smoke_fallback.py"
run_step "Model gating smoke" python "$ROOT_DIR/scripts/e2e_model_gating_smoke.py"
run_step "RAG document management" python "$ROOT_DIR/scripts/e2e_rag_document_management.py"
run_step "Job queue processing" python "$ROOT_DIR/scripts/e2e_job_queue_processing.py"

printf '[ok] All configured E2E scripts completed\n'
