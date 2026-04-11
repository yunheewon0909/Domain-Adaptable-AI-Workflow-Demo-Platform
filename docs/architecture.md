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
- plc routes for suite import, testcase listing, run enqueueing, run review, dashboard summary, and normalization preview
- `/demo` for the co-hosted static reviewer UI

### Worker / Queue

The `jobs` table is still the queue. Jobs move through:

- `queued`
- `running`
- `succeeded`
- `failed`

The worker claims queued rows from Postgres, then dispatches runner modules via subprocess. That pattern is shared by both reviewer workflows and PLC runs.

### PLC Domain Slice

The PLC MVP adds:

- `plc_test_suites` table for imported normalized suite definitions
- `plc_test_run` job type in `jobs`
- deterministic executor seam under `api.services.plc`
- exact-match validator logic inside the PLC runner path

The initial schema intentionally stores normalized cases inside `definition_json` rather than fully normalizing cases/results into many tables. That keeps the MVP compact while preserving a clean migration path later.

## PLC Flow

1. User uploads CSV/XLSX suite
2. Import service normalizes rows into suite JSON and stores them in `plc_test_suites`
3. User creates a PLC run for a suite or testcase subset
4. API inserts a `plc_test_run` row into `jobs`
5. Worker claims the job and dispatches `api.services.plc.job_runner`
6. Runner loads payload, executes the stub or CLI-backed executor, validates expected vs actual outputs, and aggregates testcase results
7. Worker stores the structured result back into `jobs.result_json`
8. `/demo` and PLC APIs read those stored results for review

## Deterministic Validation

The validator is deliberately rule-based:

- `actual_output == expected_output`
- type mismatch becomes an explicit failure reason
- executor/runtime problems are handled separately from testcase mismatches

This means:

- a run with failed testcases can still be a successful queue job
- a broken parser, missing CLI, or invalid executor payload becomes a failed queue job

## LLM Assist Placement

LLMs remain a sidecar capability, not a PLC control plane.

Allowed future roles:

- testcase normalization suggestions
- missing-field detection
- description generation
- failure-log summarization
- search and maintenance assistance

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

That is what turns the repo from “workflow demo only” into “skeleton + demo + service” without a destabilizing rewrite.
