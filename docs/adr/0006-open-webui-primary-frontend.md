# ADR 0006: Open WebUI is the primary frontend

## Status

Accepted (2026-06). Part of the Docker-first redirect (see `docs/open-webui-docker-migration.md`).

## Context

The repo shipped a bespoke `/demo` chat UI (a vanilla-JS wizard) that duplicated functionality
Open WebUI already does far better (chat, model picker, streaming, RAG toggles). Maintaining a
competing chat surface was effort spent away from the differentiating backend (domain Graph RAG +
evaluation).

## Decision

- **Open WebUI is the primary user-facing UI**, bundled as a container in `compose.yml` and
  pointed at the API's OpenAI-compatible `/v1/*` surface.
- The API exposes its domain capabilities to Open WebUI as an **importable tool**
  (`/openwebui/platform_tools.py` + `/openwebui/manifest.json`).
- **`/demo` is demoted** to an admin / evaluation / debug dashboard. It must not be a chat UI and
  must not compete with Open WebUI.

## Consequences

- We stop investing in chat UX and invest in the backend tool surface instead.
- Users get a mature chat experience for free; our value shows up as tools and reports inside it.
- ADR 0004 (Open WebUI as an optional sidecar/integration) is superseded — it is now primary.
