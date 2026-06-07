# ADR 0008: Remove fine-tuning from the core product

## Status

Accepted (2026-06). Supersedes ADR 0005's MLX QLoRA focus.

## Context

The product's headline was MLX QLoRA fine-tuning served through LM Studio. In practice this tied
the whole platform to Apple Silicon + a specific serving runtime, carried a large surface (trainer
backends, artifact publishing, model registry readiness gating, LM Studio symlink/load, an
LLM-as-Judge verifier), and overlapped poorly with the Docker-first direction. The genuinely
valuable, portable capability is **domain RAG + evaluation**, not training.

## Decision

- **Remove fine-tuning from the core**: the MLX trainer, `/ft-*` routes, fine-tuning UI (demo
  steps 2–5), model-artifact publishing, the deterministic smoke trainer, the LM Studio
  symlink/register flow, and the Step-5 `/inference/verify-job` LLM-as-Judge.
- **Drop the fine-tuning tables** (`ft_datasets`, `ft_dataset_versions`, `ft_dataset_rows`,
  `ft_training_jobs`, `ft_model_artifacts`, and the `model_registry.artifact_id` FK) in a single
  migration alongside the code removal (with a downgrade path).
- **Keep the Q/A generator**, repurposed as **evaluation/testset generation** (ADR ...,
  `services/evaluation/`).

## Consequences

- The platform no longer depends on MLX, training subprocesses, or a serving runtime that can host
  fine-tunes.
- Existing fine-tuning data is discarded (demo-scale; downgrade recreates empty tables).
- The model registry's fine-tune-specific semantics go away; model listing comes from the runtime
  adapter.
- Do not reintroduce fine-tuning into the core.
