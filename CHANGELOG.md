# Changelog

All notable changes to this repository will be documented in this file.

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
