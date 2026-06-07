# ADR 0011: AgentDocker-safe development vs host runtime verification

## Status

Accepted (2026-06).

## Context

Development happens inside **AgentDocker**, a Docker-based agent container whose default safety
model intentionally avoids host bind mounts and does **not** mount the host Docker socket. So the
Docker daemon is not reachable from inside AgentDocker, and Docker-in-Docker / privileged mode are
off the table. PyYAML is also not installed in the dev container. Yet the product is Docker-first,
so "does it run?" is inherently a host question.

## Decision

Split verification into two explicit classes, and label every check by class.

- **AgentDocker-safe (run in-container):** repo inspection, `git` status/diff, unit tests (sqlite
  + faked runtime), `rg` doc/code greps, `bash -n` and `python -m py_compile` syntax checks, and
  compose **structure** checks via `rg` (service/volume names) — not YAML parsing (PyYAML absent).
- **Host runtime (the user runs on macOS + Docker Desktop):** `docker compose config` / `up`,
  service health on :8000/:3000/:11434/:5432, browser + Open WebUI tool import, model pull +
  inference against the Ollama container, full E2E scripts.

Rules: never require Docker-in-Docker or the host socket; if Docker is unavailable in AgentDocker
that is expected, not a failure; **never claim host runtime validation passed unless it actually
ran and the output was inspected.** Every report separates (1) AgentDocker-safe checks run,
(2) host checks not run, (3) exact host commands, (4) expected success signals, (5) limitations.

## Consequences

- E2E and compose work is authored and statically validated in-container, then handed to the user
  with exact commands and expected signals.
- A docker-control profile (host socket access) could later enable in-agent runtime checks, but
  only with explicit user approval — out of scope here.
