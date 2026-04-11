# ADR 0003: Use directory separation to show skeleton, demo, service, and shared core in one repo

## Status

Accepted

## Context

The repository needs to communicate both platform reuse and real domain implementation, without splitting the story across long-lived branches.

## Decision

Keep one repository and one mainline history, and make role boundaries visible with directory and documentation structure instead of branch separation.

## Consequences

- reviewers can understand the whole platform in one tree
- the skeleton-to-service integration points stay explicit
- future domains can be added beside the PLC slice
- the repo evolves as a monorepo-style modular monolith rather than a set of diverging branches
