# Architecture

## Current Shape

This repository is a modular monolith organized as a uv workspace with two runtime apps:

- `apps/api`: HTTP surface, domain services, static reviewer UI, job runner modules
- `apps/worker`: queue claim/retry loop and subprocess dispatch

Postgres remains the system of record for queue state and operational metadata. Local retrieval artifacts still use SQLite/JSON for the reviewer workflow slice. The new PLC slice does not replace that existing reviewer architecture; it adds a second domain surface that uses the same queue and demo infrastructure.

## Main Components

### API

The FastAPI app assembles small routers under `apps/api/src/api/routers/` and includes:

- datasets/workflows/jobs/rag from the original reviewer flow
- plc routes for suite import, testcase listing, target-aware run enqueueing, run review, dashboard summary, normalization preview, and persisted suggestion review
- `/demo` for the co-hosted static reviewer UI

### Worker / Queue

The `jobs` table is still the queue. Jobs move through:

- `queued`
- `running`
- `succeeded`
- `failed`

The worker claims queued rows from Postgres, then dispatches runner modules via subprocess. That pattern is shared by both reviewer workflows and PLC runs.

### PLC Domain Slice

The PLC slice now adds:

- `plc_test_suites` for suite headers and import provenance snapshots
- `plc_testcases` for relational testcase master rows
- `plc_test_runs` for PLC run headers linked to queue jobs
- `plc_test_run_items` for testcase-level execution results
- `plc_test_run_io_logs` for ordered raw I/O review data
- `plc_targets` for lightweight target registry metadata
- `plc_llm_suggestions` for reviewable suggestion persistence
- `plc_test_run` job type in `jobs`
- deterministic executor seam under `api.services.plc`, with a versioned future CLI contract
- exact-match validator logic inside the PLC runner path

The current architecture is intentionally hybrid: relational tables now hold the primary PLC review data, while `plc_test_suites.definition_json` and `jobs.result_json` remain as compatibility/provenance snapshots during the migration away from the compact JSON-only MVP. `definition_json` is now explicitly narrower: it remains suite provenance plus a compatibility fallback only when relational testcase rows are missing. Partial relational drift is treated as an operational error during run creation rather than a silent fallback case.

## PLC Flow

1. User uploads CSV/XLSX suite
2. Import service normalizes rows into suite JSON, stores suite provenance in `plc_test_suites`, and writes relational testcase rows into `plc_testcases`
3. User creates a PLC run for a suite or testcase subset
4. API inserts a `plc_test_run` row into `jobs` and materializes matching `plc_test_runs` plus queued `plc_test_run_items`
5. API validates that the selected target exists, is active, and matches the configured executor mode before queue rows are created
6. Worker claims the job and dispatches `api.services.plc.job_runner`
7. Runner loads payload, executes the stub or CLI-backed executor, validates expected vs actual outputs, and persists testcase/item results plus I/O logs into relational PLC tables
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
- `timeout_ms`
- `target_key`
- `testcase_metadata`
- `execution_context`

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

## LLM Assist Placement

LLMs remain a sidecar capability, not a PLC control plane.

Allowed future roles:

- testcase normalization suggestions
- missing-field detection
- description generation
- failure-log summarization
- search and maintenance assistance

Current implemented role:

- persisted normalization suggestions with explicit `pending` / `accepted` / `rejected` review state

Forbidden roles:

- deciding PLC write/read sequences at runtime
- deciding final pass/fail verdicts
- driving retry policy or queue orchestration

## Why This Still Fits the Skeleton

The important architectural decision is reuse rather than replacement:

- reuse the existing queue
- reuse the existing worker subprocess pattern
- reuse the co-hosted reviewer UI
- add a domain service slice inside the current monorepo shape
- separate queue lifecycle state from PLC domain review state without introducing a second queue

That is what turns the repo from “workflow demo only” into “skeleton + demo + service” without a destabilizing rewrite.
