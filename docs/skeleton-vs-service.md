# Skeleton vs Service

## Why this repository is not just a demo anymore

Originally, this repo functioned mainly as a reviewer workflow skeleton: FastAPI, worker, queue, local retrieval, and a small `/demo` page. With the PLC testing MVP and the new local AI ops expansion, it now also contains concrete domain services that demonstrate how the skeleton can host real operational workflows.

That matters because the intended long-term shape is a single monorepo that can hold:

- reusable platform skeleton pieces
- reviewer/demo surfaces
- one or more concrete domain services

## Responsibility Boundaries

### Skeleton

The skeleton is the reusable operational frame:

- workspace layout
- API app assembly
- Postgres-backed queue pattern
- worker heartbeat and retry behavior
- static `/demo` hosting

These are the pieces another domain could reuse later.

### Demo / Reviewer

The demo is the co-hosted reviewer surface under `/demo`.

It exists to make the repository explorable and reviewable without introducing a separate frontend app. In this repo it now supports five reviewer modes:

- retrieval-first workflow review
- PLC suite/run/result review
- fine-tuning dataset and version review
- real local training job, artifact, and publish-readiness review
- model registry plus model-selectable inference review
- RAG collection/document/retrieval preview review

### Service / Domain

The repo now has multiple concrete domain slices:

- PLC testing under `apps/api/src/api/services/plc/`
- local AI ops slices under `apps/api/src/api/services/fine_tuning/`, `apps/api/src/api/services/model_registry/`, and the expanded `apps/api/src/api/services/rag/`

These are intentionally not split into separate repositories or long-lived branches. They live beside the reviewer skeleton so the repo can show both the reusable platform and multiple real domain implementations.

The PLC service is no longer just an import-and-JSON demo. It now demonstrates a more operational shape:

- spreadsheet import into suite headers plus testcase master rows
- execution profile scaffolding plus request snapshot persistence before any native adapter work
- queue-backed run orchestration
- relational run item and raw I/O persistence
- target-aware queue validation, normalized target metadata, and a versioned future CLI execution seam
- review-oriented APIs and demo panels layered on top of those records
- persisted LLM suggestion review artifacts that stay outside the deterministic execution path
- explicit relational-first review boundaries, with `definition_json` fallback surfaced as compatibility rather than hidden primary behavior
- separate fine-tuning dataset/version/row review, real training orchestration, artifact registration, publish-ready serving seams, and model selection flows for local AI ops
- separate RAG collection/document management so grounding data can evolve independently from fine-tuning corpora

### Shared Core

`shared/` remains the placeholder for framework-agnostic interfaces and future extracted core contracts. The repo does not force a premature package split yet, but it makes the shared-core boundary visible now so later services have an obvious place to converge on common contracts such as queue/domain separation rules, execution envelopes, and reusable review contracts.

## Why directory separation instead of long-lived branches

Long-lived “skeleton branch” and “service branch” approaches make the platform story harder to understand. They also hide the actual integration points between platform and service code.

Directory separation is better here because:

- reviewers can inspect the whole system in one checkout
- the shared seams stay explicit
- feature history remains milestone-based instead of branch-based
- the final desired state is visible on `main`

## What this repo now demonstrates

This repository now demonstrates that the same underlying skeleton can support:

- knowledge/reviewer workflows
- deterministic industrial test automation workflows
- local AI ops workflows such as fine-tuning data review, real local training execution, artifact/publish-readiness review, model selection, and RAG collection management

without changing deployment shape, abandoning the queue model, or introducing a second frontend stack.

That distinction matters in the current PLC milestone. The repo is still a skeleton in the sense that the worker, queue, API assembly, and static shell are reusable. It is also clearly a service now because the PLC slice has its own relational model, execution profile scaffolding, validation rules, future native execution contract, target registry rules, and reviewer-specific operational workflows.
