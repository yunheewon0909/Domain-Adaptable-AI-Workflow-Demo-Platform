# ADR 0002: Keep PLC execution deterministic and isolate native execution behind a CLI adapter seam

## Status

Accepted

## Context

The platform needs to reuse existing PLC execution assets, likely in C++, while keeping the first MVP testable end-to-end without hardware.

## Decision

The repo uses a deterministic stub executor for MVP validation and a subprocess + JSON CLI seam for future native integration. Final pass/fail remains exact-match validator logic, not an LLM decision.

## Consequences

- the worker and API path can be validated immediately
- future native integration can replace only the executor implementation
- queue behavior does not depend on hardware being present
- LLMs stay outside real-time control and verdict logic
