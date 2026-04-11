# Changelog

All notable changes to this repository will be documented in this file.

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
