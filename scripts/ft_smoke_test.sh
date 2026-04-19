#!/usr/bin/env bash

set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
DATASET_FILE="${DATASET_FILE:-examples/ft_smoke_instruction_dataset.jsonl}"
BASE_MODEL_NAME="${BASE_MODEL_NAME:-qwen2.5:7b-instruct-q4_K_M}"
TRAINER_MODEL_NAME="${TRAINER_MODEL_NAME:-hf-internal/testing-tiny-random-gpt2}"
TRAINING_METHOD="${TRAINING_METHOD:-sft_lora}"

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    printf 'Missing required file: %s\n' "$path" >&2
    exit 1
  fi
}

json_field() {
  local field="$1"
  python3 -c 'import json,sys; data=json.load(sys.stdin); print(data[sys.argv[1]])' "$field"
}

require_file "$DATASET_FILE"

cat <<EOF
Fine-tuning smoke test helper
=============================

Prerequisites:
- API and worker must already be running.
- Run ./scripts/ft_smoke_preflight.sh first so the worker runtime/device path is clear.
- Recommended on Apple Silicon: TRAINING_DEVICE=mps with a host worker runtime
- CPU smoke tests stay opt-in: TRAINING_ALLOW_CPU=true
- This flow validates adapter/report/registry output only. It does not create an Ollama serving model.

Using:
- API_BASE_URL=$API_BASE_URL
- DATASET_FILE=$DATASET_FILE
- BASE_MODEL_NAME=$BASE_MODEL_NAME
- TRAINER_MODEL_NAME=$TRAINER_MODEL_NAME
- TRAINING_METHOD=$TRAINING_METHOD
EOF

dataset_payload=$(python3 - <<'PY'
import json
print(json.dumps({
    "name": "Local FT smoke test dataset",
    "task_type": "instruction_sft",
    "schema_type": "json",
    "description": "Small local smoke-test dataset for validating the SFT+LoRA artifact pipeline.",
}))
PY
)

dataset_response=$(curl -fsS -X POST "$API_BASE_URL/ft-datasets" \
  -H 'Content-Type: application/json' \
  -d "$dataset_payload")
dataset_id=$(printf '%s' "$dataset_response" | json_field id)

version_payload=$(python3 - <<'PY'
import json
print(json.dumps({
    "version_label": "smoke-v1",
    "train_split_ratio": 0.75,
    "val_split_ratio": 0.25,
    "test_split_ratio": 0.0,
}))
PY
)

version_response=$(curl -fsS -X POST "$API_BASE_URL/ft-datasets/$dataset_id/versions" \
  -H 'Content-Type: application/json' \
  -d "$version_payload")
version_id=$(printf '%s' "$version_response" | json_field id)

rows_payload=$(python3 - "$DATASET_FILE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
rows = []
entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
for index, entry in enumerate(entries):
    split = "train"
    if len(entries) > 1 and index == len(entries) - 1:
        split = "val"
    rows.append({
        "split": split,
        "input_json": {
            "instruction": entry["instruction"],
            "input": entry.get("input", ""),
        },
        "target_json": {"output": entry["output"]},
        "metadata_json": {
            "source": "ft_smoke_test_helper",
            "smoke_test": True,
            "example_index": index + 1,
        },
    })
print(json.dumps({"rows": rows}))
PY
)

curl -fsS -X POST "$API_BASE_URL/ft-dataset-versions/$version_id/rows" \
  -H 'Content-Type: application/json' \
  -d "$rows_payload" >/dev/null

curl -fsS -X POST "$API_BASE_URL/ft-dataset-versions/$version_id/status" \
  -H 'Content-Type: application/json' \
  -d '{"status":"validated"}' >/dev/null

curl -fsS -X POST "$API_BASE_URL/ft-dataset-versions/$version_id/status" \
  -H 'Content-Type: application/json' \
  -d '{"status":"locked"}' >/dev/null

training_payload=$(python3 - <<PY
import json
print(json.dumps({
    "dataset_version_id": "$version_id",
    "base_model_name": "$BASE_MODEL_NAME",
    "training_method": "$TRAINING_METHOD",
    "hyperparams_json": {
        "epochs": 1,
        "batch_size": 1,
        "gradient_accumulation_steps": 1,
        "max_seq_length": 256,
        "lora_r": 8,
        "lora_alpha": 16,
        "lora_dropout": 0.05,
        "trainer_model_name": "$TRAINER_MODEL_NAME",
        "smoke_test": True,
    },
}))
PY
)

training_response=$(curl -fsS -X POST "$API_BASE_URL/ft-training-jobs" \
  -H 'Content-Type: application/json' \
  -d "$training_payload")
training_job_id=$(printf '%s' "$training_response" | json_field id)

cat <<EOF

Created smoke-test resources:
- dataset_id: $dataset_id
- dataset_version_id: $version_id
- training_job_id: $training_job_id

Next checks:
1. Poll: curl -sS $API_BASE_URL/ft-training-jobs/$training_job_id
2. Success means ft_training_jobs.status == succeeded
3. Confirm adapter dir exists: data/model_artifacts/$training_job_id/trainer_output/adapter/
4. Confirm training report exists: data/model_artifacts/$training_job_id/trainer_output/training_report.json
5. Confirm /models shows a fine-tuned row with status artifact_ready / publish_ready
6. Expect inference to remain blocked until a real serving model import exists
EOF
