# Architecture

## Current Shape

This repository is a modular monolith organized as a uv workspace with two runtime apps:

- `apps/api`: HTTP surface, domain services, static reviewer UI, job runner modules
- `apps/worker`: queue claim/retry loop and subprocess dispatch

Postgres remains the system of record for queue state and operational metadata. Local retrieval artifacts still use SQLite/JSON for the reviewer workflow slice. The PLC slice and the new local AI ops slice do not replace that existing reviewer architecture; they add more domain surfaces that reuse the same queue and demo infrastructure.

## Main Components

### API

The FastAPI app assembles small routers under `apps/api/src/api/routers/` and includes:

- datasets/workflows/jobs/rag from the original reviewer flow
- plc routes for suite import, testcase listing, target-aware run enqueueing, run review, dashboard summary, normalization preview, and persisted suggestion review
- fine-tuning routes for dataset registries, versioned rows, status transitions, training summaries, and training enqueueing
- model routes for training job inspection, artifact/log inspection, publish seam control, model lineage inspection, and separate registry review versus inference selection
- rag collection/document routes for collection management, upload/preview, and retrieval preview
- `/demo` for the co-hosted static reviewer UI

### Worker / Queue

The `jobs` table is still the queue. Jobs move through:

- `queued`
- `running`
- `succeeded`
- `failed`

The worker claims queued rows from Postgres, then dispatches runner modules via subprocess. That pattern is shared by reviewer workflows, PLC runs, and the new `ft_train_model` real training path.

### PLC Domain Slice

The PLC slice now adds:

- `plc_test_suites` for suite headers and import provenance snapshots
- `plc_execution_profiles` for execution profile registry scaffolding
- `plc_testcases` for relational testcase master rows
- `plc_test_runs` for PLC run headers linked to queue jobs
- `plc_test_run_items` for testcase-level execution results
- `plc_test_run_io_logs` for ordered raw I/O review data
- `plc_targets` for lightweight target registry metadata
- `plc_llm_suggestions` for reviewable suggestion persistence
- `plc_test_run` job type in `jobs`
- deterministic executor seam under `api.services.plc`, with a versioned future CLI contract
- exact-match validator logic inside the PLC runner path

The current architecture is intentionally hybrid: relational tables now hold the primary PLC review data, while `plc_test_suites.definition_json` and `jobs.result_json` remain as compatibility/provenance snapshots during the migration away from the compact JSON-only MVP. `definition_json` is now explicitly narrower: it remains suite provenance plus a compatibility fallback only when relational testcase rows are missing. Partial relational drift is treated as an operational error during run creation rather than a silent fallback case, and the fallback path is now surfaced explicitly through `case_source` / `testcase_source` markers instead of being hidden.

### Local AI Ops Slice

The AI ops expansion adds three deliberately separated surfaces:

- `ft_datasets`, `ft_dataset_versions`, and `ft_dataset_rows` for fine-tuning dataset management
- `ft_training_jobs`, `ft_model_artifacts`, and `model_registry` for queue-backed real training runs, artifact registration, publish-ready seams, and model readiness
- `rag_collections` and `rag_documents` for collection/document management that stays distinct from fine-tuning data and from the legacy dataset registry

Important boundaries in this milestone:

- Ollama remains the serving target for inference requests
- training now supports one real queue + worker path: local `sft_lora` with a PEFT/Transformers backend and explicit environment guards
- fine-tuning rows and RAG documents are stored and reviewed separately rather than merged into one generic dataset table
- fine-tuned models are visible in the registry immediately after adapter/report/manifest validation, artifact-only rows stay reviewable, and inference stays blocked until a real serving model exists
- the co-hosted `/demo` shell now exposes workflow, PLC, fine-tuning, model, and RAG reviewer modes without introducing a second frontend app

## AI Ops Flow

1. User creates a fine-tuning dataset and version.
2. Rows are validated and the version is moved from `draft` to `validated` to `locked`.
3. API inserts an `ft_training_jobs` row and a backing `ft_train_model` queue job.
4. Worker claims the job and dispatches `api.services.model_registry.job_runner`.
5. Runner exports trainer-ready JSONL snapshots under `data/model_artifacts/<job_id>/dataset_export/`.
6. Runner executes the real local `sft_lora` backend, which produces a PEFT adapter bundle plus a training report.
7. The backend validates expected adapter/report/log files before a run is allowed to finish as `succeeded`.
8. Artifact rows are written for dataset export, adapter bundle, training report, and publish manifest.
9. A `model_registry` row is created as `artifact_ready` with `publish_status=publish_ready` and explicit trainer/serving lineage metadata.
10. The current publish seam does not run a real Ollama import, so the fine-tuned row remains artifact-only until an external serving/import step exists.

## Fine-tuning lineage and readiness semantics

- `base_model_name` is the serving/base lineage chosen by the user
- `trainer_model_name` is the actual local checkpoint used by PEFT/Transformers
- a trainer/base mismatch is acceptable for a smoke test, but it must not be described as “the serving model was fine-tuned”
- `artifact_ready` means the adapter/report/manifest package exists and passed structural validation
- `publish_ready` means a reviewer-facing publish manifest/template exists
- `runtime-ready` is still false until a real serving model exists

## Apple Silicon smoke-test boundary

For local Mac verification, the intended target is a **small-model smoke test**:

- prefer `TRAINING_DEVICE=mps` when MPS is available
- keep CPU disabled by default unless `TRAINING_ALLOW_CPU=true` is set deliberately for a tiny fallback run
- validate the pipeline by checking job success, adapter output, report/log files, and the resulting `artifact_ready` registry row
- do not treat that smoke path as evidence that large-model training is practical on a MacBook Air-class machine

## PLC Flow

1. User uploads CSV/XLSX suite
2. Import service normalizes rows into suite JSON, stores suite provenance in `plc_test_suites`, materializes execution profile scaffolding in `plc_execution_profiles`, and writes relational testcase rows into `plc_testcases`
3. User creates a PLC run for a suite or testcase subset
4. API inserts a `plc_test_run` row into `jobs` and materializes matching `plc_test_runs` plus queued `plc_test_run_items`
5. API validates that the selected target exists, is active, and matches the configured executor mode before queue rows are created
6. Worker claims the job and dispatches `api.services.plc.job_runner`
7. Runner loads payload, executes the stub or CLI-backed executor, validates expected vs actual outputs, and persists testcase/item results plus I/O logs into relational PLC tables, including request snapshots needed for later review
8. Preview-only or persisted LLM suggestions remain sidecar review artifacts in `plc_llm_suggestions` and do not mutate testcase masters automatically
9. Worker keeps queue lifecycle in sync and stores a compact compatibility summary back into `jobs.result_json`
10. `/demo` and PLC APIs read relational review records first, with compatibility fallback still available only for suites whose relational testcase rows are missing

## Deterministic Validation

The validator is deliberately rule-based:

- `actual_output == expected_output`
- type mismatch becomes an explicit failure reason
- executor/runtime problems are handled separately from testcase mismatches

This means:

- a run with failed testcases can still be a successful queue job
- a broken parser, missing CLI, or invalid executor payload becomes a failed queue job

## Future CLI Adapter Integration Contract

The future native executor boundary is now explicitly versioned. The current contract is shared by the deterministic stub executor and the CLI adapter.

Request envelope fields:

- `schema_version`
- `testcase_id`
- `instruction`
- `input_type`
- `output_type`
- `inputs`
- `expected`
- `expected_outcome`
- `memory_profile_key`
- `execution_profile_key`
- `execution_profile`
- `timeout_ms`
- `target_key`
- `testcase_context`
- `run_context`
- `target_context`
- `extension_json`

Result envelope fields:

- `schema_version`
- `status`
- `write_values`
- `read_values`
- `actual_output`
- `expected_output`
- `duration_ms`
- `raw_log`
- `executor_exit_code`
- `diagnostics`
- `warning_codes`
- `executor_metadata`

The adapter treats timeout, empty stdout, invalid JSON, schema-invalid payloads, and non-zero process exits as infrastructure failures. Final testcase verdicts still belong to deterministic validator logic, not the native executor.

## Execution Metadata and Target Modeling

The repo still avoids private PLC adapter details, but it now models their future attachment points more clearly:

- `plc_execution_profiles` keeps non-secret execution metadata such as instruction name, input/output type, timeout policy, setup/reset placeholders, notes, and future address-contract placeholders
- testcase masters keep the familiar `memory_profile_key` while linking to an execution profile key
- PLC run headers snapshot request schema version, executor mode, validator version, and normalized target metadata
- PLC run items snapshot request context, input/output typing, expected outcome, and execution profile linkage
- normalized target metadata exposes `environment_label`, `line`, `bench`, `tags`, and extra non-secret attributes while still avoiding credentials and live connection details

That combination preserves the deterministic execution path while making future adapter integration much less implicit.

## LLM Assist Placement

LLMs remain a sidecar capability, not a PLC control plane.

Allowed future roles:

- testcase normalization suggestions
- missing-field detection
- description generation
- failure-log summarization
- search and maintenance assistance

Current implemented role:

- persisted normalization suggestions with explicit `pending` / `accepted` / `rejected` review state, payload schema versioning, and `suggestion_type` filtering

Forbidden roles:

- deciding PLC write/read sequences at runtime
- deciding final pass/fail verdicts
- driving retry policy or queue orchestration

## Why This Still Fits the Skeleton

The important architectural decision is reuse rather than replacement:

- reuse the existing queue
- reuse the existing worker subprocess pattern
- reuse the co-hosted reviewer UI
- add multiple domain service slices inside the current monorepo shape
- separate queue lifecycle state from PLC domain review state without introducing a second queue
- separate fine-tuning/model/RAG review state from generic jobs without introducing a second queue or frontend

That is what turns the repo from “workflow demo only” into “skeleton + demo + services” without a destabilizing rewrite.
