# ADR 0007: Docker-only default runtime path

## Status

Accepted (2026-06). Supersedes ADR 0005's Mac-native runtime decision.

## Context

ADR 0005 dropped Docker for a Mac-native stack (brew Postgres, MLX, LM Studio). That made the
product unusable for anyone not on Apple Silicon with a specific local toolchain, and made
onboarding a multi-step manual runbook. The new product must be runnable by a basic user with one
command.

## Decision

- **`docker compose up` is the only required path.** `compose.yml` provides `postgres`, `ollama`,
  `open-webui`, `api`, and `worker`. The default runtime is the **Ollama container** for both chat
  and embeddings.
- **No Homebrew, MLX, or LM Studio** is required for the default path.
- Native runtimes (LM Studio, native Ollama, any OpenAI-compatible endpoint) are **optional
  configuration** via the runtime adapter (ADR 0009), never the default.
- API/worker images use `python:3.12-slim` for broad wheel availability; code stays 3.11+
  compatible so local dev on 3.14 keeps working.

## Consequences

- Cross-platform onboarding becomes one command + two `ollama pull`s.
- We re-introduce the compose/worker shape removed in ADR 0005 (commit `ffca9a8`), now without the
  fine-tuning worker payload.
- Inside AgentDocker the Docker daemon is unavailable; compose/runtime validation is host-side
  (ADR 0011).
