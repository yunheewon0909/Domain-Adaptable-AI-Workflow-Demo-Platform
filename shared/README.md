# Shared Core Boundary

`shared/` is the visible shared-core seam for this repository.

Today it stays intentionally light. The goal is not to force early extraction into a third workspace package before the reuse pressure is real. Instead, this directory documents where framework-agnostic contracts and utilities should move once multiple domain services genuinely share them.

Current role:

- mark the shared-core boundary in the repo structure
- hold cross-app documentation or interfaces that should not belong to one service
- avoid premature package splitting while still making the monorepo direction visible

Future candidates for `shared/`:

- queue/job contracts reused across services
- execution envelope schemas
- generic artifact metadata contracts
- framework-agnostic helper interfaces
