# Skeleton vs Service

## Why this repository is not just a demo anymore

Originally, this repo functioned mainly as a reviewer workflow skeleton: FastAPI, worker, queue, local retrieval, and a small `/demo` page. With the PLC testing MVP, it now also contains a concrete domain service that demonstrates how the skeleton can host real operational workflows.

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

It exists to make the repository explorable and reviewable without introducing a separate frontend app. In this repo it now supports two reviewer modes:

- retrieval-first workflow review
- PLC suite/run/result review

### Service / Domain

The domain service is the new PLC testing slice under `apps/api/src/api/services/plc/` plus its routes, migration, tests, and worker job type.

This is intentionally not split into a separate repository or long-lived branch. It lives beside the reviewer skeleton so the repo can show both the reusable platform and one real domain implementation.

### Shared Core

`shared/` remains the placeholder for framework-agnostic interfaces and future extracted core contracts. The repo does not force a premature package split yet, but it makes the shared-core boundary visible now so later services have an obvious place to converge on common contracts.

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

without changing deployment shape, abandoning the queue model, or introducing a second frontend stack.
