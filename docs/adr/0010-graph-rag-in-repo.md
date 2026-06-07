# ADR 0010: In-repo Graph RAG (Postgres + networkx), not Microsoft graphrag

## Status

Accepted (2026-06).

## Context

RAG is now the core capability, and the user wants **Graph RAG** specifically. Today's RAG is
preview-only: one `text_preview` (≤4 KB) + one embedding per document in `metadata_json`, with
cosine/lexical retrieval over previews — not a real chunk/graph index. Microsoft's `graphrag`
PyPI package is the obvious off-the-shelf option but pulls heavy deps (`pandas`, `graspologic`,
`numba`) with uncertain Python-3.14 wheels and imposes a file-based pipeline that fights our
Postgres + job-queue architecture.

## Decision

Implement a **lean in-repo GraphRAG**:

- **Storage:** Postgres property-graph tables — `rag_chunks`, `rag_entities`, `rag_relationships`,
  `rag_entity_chunks`, `rag_communities` (+ members), `rag_query_traces`. Embeddings stored as
  JSON; cosine in pure Python at demo scale. `pgvector` is an optional advanced toggle, not the
  default.
- **Graph algorithms:** `networkx` (pure Python, no native deps) —
  `greedy_modularity_communities` for community detection (no Leiden/graspologic).
- **LLM extraction + embeddings:** via the runtime adapter (ADR 0009), as **worker jobs**:
  `parse → chunk → embed_chunks → extract_graph → detect_communities → summarize_communities`.
- **Retrieval:** local (graph expansion), global (community-summary map-reduce), naive (chunk
  vector) — every query writes a `rag_query_traces` evidence row.

## Consequences

- No exotic infrastructure; the default Docker path builds graphs with just Postgres + Ollama +
  `networkx`.
- Graph construction is LLM-heavy and async (worker); a naive fallback answers before it finishes.
- Stored traces make retrieval auditable and power the evaluation phase.
- If true vector search is later needed at scale, `pgvector` can be enabled without reworking the
  schema (embeddings already columnar).
