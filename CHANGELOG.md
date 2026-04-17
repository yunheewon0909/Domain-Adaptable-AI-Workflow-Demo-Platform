# Changelog

All notable changes to this repository will be documented in this file.

## [0.7.0] - 2026-04-17

### Added

- real `sft_lora` training execution behind the existing `ft_train_model` queue and worker path
- trainer-ready dataset export formatting for `instruction_sft`, `chat_sft`, and `prompt_completion`
- richer `ft_training_jobs` metadata including trainer backend, split counts, format summary, metrics, evaluation seam, error payloads, and output directory tracking
- real fine-tuning artifact rows for dataset export, adapter bundles, training reports, and publish manifests
- model readiness metadata including published model names, publish status, and lineage payloads
- new AI ops endpoints for dataset version summaries, artifact detail, model lineage, training logs, and publish-step control
- `.env.example` entries for local training and publish-seam configuration

### Changed

- fine-tuning no longer stops at a placeholder manifest; successful runs now create real local artifacts and register tuned models as `artifact_ready`
- inference no longer silently routes fine-tuned registry entries back through the base model; artifact-only rows are visible but blocked until `published`
- the `/demo` Fine-tuning and Models surfaces now distinguish training phases, artifact counts, base lineage, publish status, and selection eligibility
- workspace, API, and worker package versions bumped from `0.6.0` to `0.7.0`

### Notes

- Ollama remains a serving target, not the trainer itself
- the built-in trainer path is intentionally narrow: one local `sft_lora` route with explicit device/dependency guards
- the publish/import flow is still a truthful seam rather than a claim of full automatic Ollama packaging for every artifact shape

## [0.6.0] - 2026-04-17

### Added

- relational fine-tuning dataset tables, versioned rows, validation state, and APIs under `/ft-datasets` and `/ft-dataset-versions`
- queue-backed `ft_train_model` orchestration with worker dispatch, lightweight artifact manifests, and `ft_training_jobs` state tracking
- model registry records plus `/models` and `/inference/run` APIs so inference can select a base or fine-tuned registry entry
- separate `rag_collections` and `rag_documents` metadata tables plus collection/document/retrieval preview APIs that do not mix with fine-tuning data
- new `/demo` reviewer modes for Fine-tuning, Models, and RAG inside the existing co-hosted static shell

### Changed

- the repo now presents PLC automation and local AI ops management as parallel domain slices on the same modular monolith and jobs queue
- Ollama remains documented as a serving target for inference while training stays a separate scaffolded pipeline handled by the queue and worker
- README, architecture docs, skeleton/service notes, changelog, and workspace package versions now describe the AI ops reviewer expansion and current limitations honestly
- workspace, API, worker, and starter app versions bumped from `0.5.0` to `0.6.0`

### Notes

- fine-tuning remains a lightweight scaffold in this milestone: dataset management, job orchestration, artifact registration, and model selection are end-to-end, but no heavy trainer backend is wired in yet
- fine-tuned registry entries currently point back to the configured Ollama serving model name until a future artifact import/publish step is implemented
- RAG collection management is intentionally separate from the legacy dataset-backed retrieval flow and currently uses metadata/text preview plus retrieval preview rather than a full collection embedding pipeline

## [0.5.0] - 2026-04-15

### Added

- `plc_execution_profiles` plus testcase linkage so execution metadata is explicit before any real native adapter work
- PLC run and run-item request snapshots covering execution profile, target context, and reviewable request metadata
- normalized target metadata with environment, line, bench, and tags surfaced through `/plc-targets`
- richer PLC dashboard summary data for target status and instruction failure concentration
- `payload_schema_version` on persisted PLC LLM suggestions plus `suggestion_type` filtering
- explicit `case_source` and `testcase_source` markers so relational vs fallback review paths are visible

### Changed

- PLC execution request envelopes moved from loose metadata dicts toward typed run/testcase/target context fields
- PLC reviewer UI now supports suite-scoped dashboard refresh, richer testcase filters, target-aware run filters, stronger run drill-down, and sequence-oriented I/O review without leaving the static co-hosted shell
- PLC target validation now rejects non-object target metadata before queue rows are written
- persisted PLC suggestion reviews are now immutable once they leave `pending`, keeping accepted/rejected artifacts reviewable instead of silently mutable
- README, architecture docs, skeleton/service notes, and package versions now describe the new execution profile scaffolding, target normalization, fallback markers, and reviewer hardening
- workspace and app versions bumped from `0.4.0` to `0.5.0`

### Notes

- deterministic validation remains the only final pass/fail authority
- native PLC execution is still not implemented in-repo; this milestone hardens the model, review UX, and fallback boundaries before any private adapter work
- persisted LLM suggestions remain review artifacts only and are not auto-applied to testcase masters

## [0.4.0] - 2026-04-12

### Added

- versioned PLC execution request/result envelopes shared by the deterministic stub executor and the future CLI adapter seam
- stricter CLI adapter error handling for timeout, empty stdout, invalid JSON, schema-invalid payloads, and non-zero process exits
- persisted `plc_llm_suggestions` storage plus list/detail/review endpoints for normalization review artifacts
- richer PLC reviewer UI controls for target selection, testcase/run/item filtering, run lifecycle visibility, item comparison views, suggestion review, and structured I/O log drill-down

### Changed

- PLC run enqueueing now validates that the selected target exists, is active, and matches the configured executor mode before queue rows are written
- `stub-local` remains visible as a built-in compatibility target even when database-backed targets exist
- relational testcase rows now drive normal PLC list and run selection flows, with `plc_test_suites.definition_json` narrowed to provenance plus explicit compatibility fallback
- executor-reported failed case results now surface as item-level errors instead of silently falling through deterministic validation
- README, architecture docs, skeleton/service notes, and ADR 0002 now describe the current CLI contract, target rules, suggestion review flow, and reviewer surface
- workspace and app versions bumped from `0.3.0` to `0.4.0`

### Notes

- deterministic validation remains the only final pass/fail authority
- persisted LLM suggestions are review artifacts only and are not auto-applied to testcase masters
- native PLC execution is still not implemented in-repo; this milestone hardens the integration contract and reviewer workflows around that future seam

## [0.3.0] - 2026-04-12

### Added

- relational PLC domain tables for testcase masters, run headers, run items, I/O logs, and target registry
- queued PLC run materialization so `POST /plc-test-runs` creates job, run, and queued run items together
- PLC run result persistence from the runner into relational tables, with worker lifecycle sync for queued/running/succeeded/failed states
- PLC API endpoints for target discovery and run-level I/O log review

### Changed

- PLC imports now dual-write suite provenance into `plc_test_suites.definition_json` and testcase masters into `plc_testcases`
- PLC testcase listing and run payload creation now read relational testcase rows first, with legacy JSON fallback kept for compatibility
- `/demo` PLC panels now surface queued/running counts alongside pass/fail/error summary cards
- PLC job `result_json` is now treated as a compact compatibility summary instead of the primary review surface
- workspace and app versions bumped from `0.2.0` to `0.3.0`

### Notes

- `jobs` remains the queue and authoritative lifecycle table; PLC run tables mirror that lifecycle for domain reviewability
- deterministic stub execution remains the default, and the future CLI adapter seam stays intact
- suite `definition_json` remains in place as import provenance and rollback-friendly compatibility data

## [0.2.0] - 2026-04-11

### Added

- PLC test automation MVP with CSV/XLSX suite import
- `plc_test_run` job type on the existing Postgres-backed queue
- deterministic stub executor and future CLI adapter seam
- PLC suite storage and testcase normalization service
- PLC run/result/dashboard APIs
- expanded co-hosted `/demo` surface for PLC suite review and run drill-down
- architecture docs, monorepo role notes, ADRs, and changelog-based milestone tracking

### Changed

- repo presentation now reflects skeleton + reviewer demo + domain service + shared core boundaries
- starter demo metadata now describes both workflow review and PLC testing review
- workspace and app versions bumped from `0.1.0` to `0.2.0`

### Notes

- PLC execution remains deterministic and stubbed in-repo
- LLMs remain outside PLC control and final pass/fail decisions

## [0.1.0] - 2026-03-08

### Added

- FastAPI reviewer workflow skeleton
- Postgres-backed jobs queue and worker
- retrieval-first workflow execution
- co-hosted `/demo` reviewer UI
- starter-definition based workflow and dataset defaults
