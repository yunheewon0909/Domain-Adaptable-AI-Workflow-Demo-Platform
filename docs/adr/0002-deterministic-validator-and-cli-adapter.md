# ADR 0002: Keep PLC execution deterministic and isolate native execution behind a CLI adapter seam

## Status

Accepted

## Context

The platform needs to reuse existing PLC execution assets, likely in C++, while keeping the first MVP testable end-to-end without hardware.

## Decision

The repo uses a deterministic stub executor for MVP validation and a subprocess + JSON CLI seam for future native integration. Final pass/fail remains exact-match validator logic, not an LLM decision.

The CLI seam is now explicitly versioned and contract-driven. Native executors receive a structured request envelope with testcase metadata and execution context, and they return observed execution results plus diagnostics. Timeout, invalid JSON, empty stdout, schema-invalid payloads, and non-zero exits are treated as infrastructure failures outside validator-owned testcase verdicts.

## Consequences

- the worker and API path can be validated immediately
- future native integration can replace only the executor implementation
- queue behavior does not depend on hardware being present
- LLMs stay outside real-time control and verdict logic
- target-aware execution context can flow into native adapters without moving queue or validator authority into the adapter layer
