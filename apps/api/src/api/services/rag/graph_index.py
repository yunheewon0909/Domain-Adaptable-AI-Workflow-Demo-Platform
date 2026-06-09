"""Graph RAG indexing pipeline (ADR 0010).

parse -> chunk -> embed_chunks -> extract_graph -> detect_communities ->
summarize_communities, persisted into the Postgres property-graph tables.

The LLM extraction and community summarization are injectable so the pipeline
is fully testable offline; embeddings degrade to ``None`` (callers fall back to
lexical scoring) when the runtime is unreachable.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from api.services.jobs import JobControl

import networkx as nx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models import (
    RAGChunkRecord,
    RAGCommunityMemberRecord,
    RAGCommunityRecord,
    RAGDocumentRecord,
    RAGEntityChunkRecord,
    RAGEntityRecord,
    RAGRelationshipRecord,
)
from api.services.rag.embedding_client import EmbeddingClientError
from api.services.runtime import get_chat_runtime, get_embedding_runtime
from api.llm import LLMClientError

# An extractor maps one chunk of text to {"entities": [...], "relationships": [...]}.
Extractor = Callable[[str], dict[str, Any]]
# A summarizer maps (entity dicts, relationship dicts) to (title, summary).
Summarizer = Callable[[list[dict[str, Any]], list[dict[str, Any]]], tuple[str, str]]


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks on a character budget.

    Prefers to break on paragraph/sentence boundaries near the budget so chunks
    stay coherent. Returns [] for empty/whitespace input.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    # Clamp overlap to a sane range so the window always makes forward progress.
    overlap = max(0, min(overlap, chunk_size - 1))
    n = len(text)
    chunks: list[str] = []
    start = 0
    while start < n:
        end = min(n, start + chunk_size)
        window = text[start:end]
        if end < n:
            # Try to break on the last paragraph or sentence boundary.
            for sep in ("\n\n", ". ", "\n", " "):
                idx = window.rfind(sep)
                if idx >= chunk_size // 2:
                    window = window[: idx + len(sep)]
                    break
        consumed = len(window)
        piece = window.strip()
        if piece:
            chunks.append(piece)
        # Stop once this window reaches the end of the text. Otherwise advance by
        # the characters actually consumed minus the overlap — never by a fixed
        # `step`, which could skip past un-emitted characters when a boundary
        # break trims the window shorter than the step (silent data loss).
        if start + consumed >= n:
            break
        start += max(1, consumed - overlap)
    return chunks


def _embed_many(texts: list[str]) -> tuple[list[list[float] | None], str | None]:
    """Embed texts via the runtime; degrade to all-None when unavailable."""
    settings = get_settings()
    model = (settings.llm_embed_model or "").strip()
    if not model or not texts:
        return [None] * len(texts), None
    try:
        vectors = get_embedding_runtime().embed_texts(texts)
    except EmbeddingClientError:
        return [None] * len(texts), None
    if len(vectors) != len(texts):
        return [None] * len(texts), None
    return list(vectors), model


# --- default LLM-backed extractor + summarizer --------------------------

_EXTRACT_INSTRUCTION = (
    "Extract a knowledge graph from the CONTEXT. Respond with ONLY a JSON object "
    '{"entities": [{"name": str, "type": str, "description": str}], '
    '"relationships": [{"source": str, "target": str, "description": str}]}. '
    "Use entity names exactly as they appear. No prose, no markdown."
)


def _parse_graph_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {"entities": [], "relationships": []}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"entities": [], "relationships": []}
    if not isinstance(data, dict):
        return {"entities": [], "relationships": []}
    entities = data.get("entities") if isinstance(data.get("entities"), list) else []
    rels = data.get("relationships") if isinstance(data.get("relationships"), list) else []
    return {"entities": entities, "relationships": rels}


def runtime_extractor(chunk: str) -> dict[str, Any]:
    """Default extractor: ask the chat runtime for graph JSON. Empty on failure."""
    try:
        result = get_chat_runtime().generate_answer(
            question=_EXTRACT_INSTRUCTION, context=chunk, temperature=0, max_tokens=2048
        )
    except LLMClientError:
        return {"entities": [], "relationships": []}
    return _parse_graph_json(result.answer)


def deterministic_summarizer(
    entities: list[dict[str, Any]], relationships: list[dict[str, Any]]
) -> tuple[str, str]:
    names = [e.get("name", "") for e in entities if e.get("name")]
    title = names[0] if names else "Community"
    summary = (
        f"Community of {len(entities)} entities "
        f"({', '.join(names[:8])}{'…' if len(names) > 8 else ''}) "
        f"with {len(relationships)} relationships."
    )
    return title, summary


def _clear_collection_graph(session: Session, collection_id: str) -> None:
    """Remove a collection's existing graph so (re)indexing is idempotent.

    The link tables (entity_chunks / community_members) have no collection_id, so
    they are cleared by membership in THIS collection's entities/chunks/
    communities — never globally — so reindexing one collection cannot wipe
    another collection's graph links.
    """
    entity_ids = select(RAGEntityRecord.id).where(
        RAGEntityRecord.collection_id == collection_id
    )
    chunk_ids = select(RAGChunkRecord.id).where(
        RAGChunkRecord.collection_id == collection_id
    )
    community_ids = select(RAGCommunityRecord.id).where(
        RAGCommunityRecord.collection_id == collection_id
    )
    session.execute(
        delete(RAGEntityChunkRecord).where(
            RAGEntityChunkRecord.entity_id.in_(entity_ids)
            | RAGEntityChunkRecord.chunk_id.in_(chunk_ids)
        )
    )
    session.execute(
        delete(RAGCommunityMemberRecord).where(
            RAGCommunityMemberRecord.community_id.in_(community_ids)
            | RAGCommunityMemberRecord.entity_id.in_(entity_ids)
        )
    )
    session.execute(
        delete(RAGRelationshipRecord).where(
            RAGRelationshipRecord.collection_id == collection_id
        )
    )
    session.execute(
        delete(RAGCommunityRecord).where(
            RAGCommunityRecord.collection_id == collection_id
        )
    )
    session.execute(
        delete(RAGEntityRecord).where(RAGEntityRecord.collection_id == collection_id)
    )
    session.execute(
        delete(RAGChunkRecord).where(RAGChunkRecord.collection_id == collection_id)
    )
    session.commit()


def index_collection(
    session: Session,
    *,
    collection_id: str,
    extractor: Extractor | None = None,
    summarizer: Summarizer | None = None,
    control: JobControl | None = None,
) -> dict[str, Any]:
    """Build the knowledge graph for one collection. Idempotent (reindex).

    ``control`` (optional) is checked at each chunk/community so a cancel or
    timeout can abort cleanly. The check before ``_clear_collection_graph``
    means an early abort leaves the existing graph intact (the clear commits).
    """
    extractor = extractor or runtime_extractor
    summarizer = summarizer or deterministic_summarizer

    documents = list(
        session.scalars(
            select(RAGDocumentRecord).where(
                RAGDocumentRecord.collection_id == collection_id
            )
        ).all()
    )

    if control is not None:
        control.check()  # abort before destroying the existing graph
    _clear_collection_graph(session, collection_id)

    settings = get_settings()

    # 1. chunk + embed
    chunk_rows: list[RAGChunkRecord] = []
    for document in documents:
        preview = (document.metadata_json or {}).get("text_preview", "")
        pieces = chunk_text(
            preview,
            chunk_size=settings.rag_chunk_size,
            overlap=settings.rag_chunk_overlap,
        )
        vectors, embed_model = _embed_many(pieces)
        for ordinal, (piece, vector) in enumerate(zip(pieces, vectors)):
            chunk_rows.append(
                RAGChunkRecord(
                    id=_new_id("rag-chunk"),
                    collection_id=collection_id,
                    document_id=document.id,
                    ordinal=ordinal,
                    text=piece,
                    token_count=len(piece.split()),
                    embedding_json=vector,
                    embedding_model=embed_model,
                )
            )
    session.add_all(chunk_rows)
    session.flush()

    # 2. extract entities + relationships per chunk; merge by normalized name
    entities_by_norm: dict[str, RAGEntityRecord] = {}
    entity_chunk_pairs: set[tuple[str, str]] = set()
    raw_relationships: list[tuple[str, str, str]] = []  # (src_norm, tgt_norm, desc)

    for chunk in chunk_rows:
        if control is not None:
            control.check()
        graph = extractor(chunk.text) or {}
        for ent in graph.get("entities", []):
            if not isinstance(ent, dict):
                continue
            name = str(ent.get("name") or "").strip()
            if not name:
                continue
            norm = _normalize_name(name)
            existing = entities_by_norm.get(norm)
            desc = str(ent.get("description") or "").strip()
            if existing is None:
                existing = RAGEntityRecord(
                    id=_new_id("rag-entity"),
                    collection_id=collection_id,
                    name=name,
                    normalized_name=norm,
                    type=str(ent.get("type") or "").strip() or None,
                    description=desc or None,
                )
                entities_by_norm[norm] = existing
            elif desc and existing.description and desc not in existing.description:
                existing.description = f"{existing.description} {desc}"
            elif desc and not existing.description:
                existing.description = desc
            entity_chunk_pairs.add((norm, chunk.id))
        for rel in graph.get("relationships", []):
            if not isinstance(rel, dict):
                continue
            src = _normalize_name(str(rel.get("source") or ""))
            tgt = _normalize_name(str(rel.get("target") or ""))
            if src and tgt and src != tgt:
                raw_relationships.append((src, tgt, str(rel.get("description") or "")))

    # Embed entity descriptions (best-effort).
    entity_list = list(entities_by_norm.values())
    if entity_list:
        descs = [e.description or e.name for e in entity_list]
        vectors, embed_model = _embed_many(descs)
        for entity, vector in zip(entity_list, vectors):
            entity.embedding_json = vector
    session.add_all(entity_list)
    session.flush()

    # entity→chunk provenance
    for norm, chunk_id in entity_chunk_pairs:
        entity = entities_by_norm.get(norm)
        if entity is not None:
            session.add(
                RAGEntityChunkRecord(entity_id=entity.id, chunk_id=chunk_id)
            )

    # 3. relationships (dedup by (src,tgt), accumulate weight)
    rel_index: dict[tuple[str, str], RAGRelationshipRecord] = {}
    for src_norm, tgt_norm, desc in raw_relationships:
        src = entities_by_norm.get(src_norm)
        tgt = entities_by_norm.get(tgt_norm)
        if src is None or tgt is None:
            continue
        key = (src.id, tgt.id)
        if key in rel_index:
            rel_index[key].weight += 1.0
        else:
            rel_index[key] = RAGRelationshipRecord(
                id=_new_id("rag-rel"),
                collection_id=collection_id,
                source_entity_id=src.id,
                target_entity_id=tgt.id,
                description=desc or None,
                weight=1.0,
            )
    session.add_all(rel_index.values())

    # degree
    degree: dict[str, int] = {}
    for (src_id, tgt_id) in rel_index:
        degree[src_id] = degree.get(src_id, 0) + 1
        degree[tgt_id] = degree.get(tgt_id, 0) + 1
    for entity in entity_list:
        entity.degree = degree.get(entity.id, 0)
    session.flush()

    # 4. community detection (networkx greedy modularity; pure Python)
    communities = _detect_communities(entity_list, list(rel_index.values()))
    community_rows: list[RAGCommunityRecord] = []
    for members in communities:
        if control is not None:
            control.check()
        member_entities = [e for e in entity_list if e.id in members]
        if not member_entities:
            continue
        member_rels = [
            r
            for r in rel_index.values()
            if r.source_entity_id in members and r.target_entity_id in members
        ]
        title, summary = summarizer(
            [{"name": e.name, "type": e.type} for e in member_entities],
            [{"description": r.description} for r in member_rels],
        )
        community = RAGCommunityRecord(
            id=_new_id("rag-comm"),
            collection_id=collection_id,
            level=0,
            title=title,
            summary=summary,
            member_count=len(member_entities),
        )
        community_rows.append(community)
        session.add(community)
        for entity in member_entities:
            entity.community_id = community.id
            session.add(
                RAGCommunityMemberRecord(
                    community_id=community.id, entity_id=entity.id
                )
            )

    # embed community summaries (best-effort)
    if community_rows:
        vectors, _ = _embed_many([c.summary or c.title or "" for c in community_rows])
        for community, vector in zip(community_rows, vectors):
            community.summary_embedding_json = vector

    session.commit()

    return {
        "collection_id": collection_id,
        "documents": len(documents),
        "chunks": len(chunk_rows),
        "entities": len(entity_list),
        "relationships": len(rel_index),
        "communities": len(community_rows),
    }


def _detect_communities(
    entities: list[RAGEntityRecord], relationships: list[RAGRelationshipRecord]
) -> list[set[str]]:
    if not entities:
        return []
    graph = nx.Graph()
    for entity in entities:
        graph.add_node(entity.id)
    for rel in relationships:
        graph.add_edge(rel.source_entity_id, rel.target_entity_id, weight=rel.weight)
    if graph.number_of_edges() == 0:
        # No edges → each connected node is its own community.
        return [{node} for node in graph.nodes]
    communities = nx.community.greedy_modularity_communities(graph, weight="weight")
    return [set(group) for group in communities]
