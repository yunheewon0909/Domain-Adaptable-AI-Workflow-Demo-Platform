"""Graph RAG retrieval (ADR 0010): local / global / naive modes.

Every query persists a ``rag_query_traces`` row recording the chunk/entity/
relationship/community evidence and scores — the substrate the evaluation phase
scores against.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models import (
    RAGChunkRecord,
    RAGCollectionRecord,
    RAGCommunityRecord,
    RAGEntityChunkRecord,
    RAGEntityRecord,
    RAGQueryTraceRecord,
    RAGRelationshipRecord,
)
from api.services.rag.collections import _cosine_similarity, _embed_text, _lexical_score

MODES = ("local", "global", "naive")
_EXCERPT_CHARS = 500


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _score_chunk(query: str, qvec: list[float] | None, chunk: RAGChunkRecord) -> float:
    if qvec and chunk.embedding_json:
        return _cosine_similarity(qvec, chunk.embedding_json)
    return _lexical_score(query, chunk.text)


def _require_collection(session: Session, collection_id: str) -> None:
    if session.get(RAGCollectionRecord, collection_id) is None:
        raise KeyError(collection_id)


def query_collection(
    session: Session,
    *,
    collection_id: str,
    query: str,
    mode: str = "local",
    top_k: int = 5,
) -> dict[str, Any]:
    _require_collection(session, collection_id)
    mode = mode if mode in MODES else "local"
    top_k = max(1, min(int(top_k), 20))
    settings = get_settings()
    embed_model = (settings.llm_embed_model or "").strip() or None
    qvec = _embed_text(query)

    if mode == "global":
        result = _global_search(session, collection_id, query, qvec, top_k)
    elif mode == "naive":
        result = _naive_search(session, collection_id, query, qvec, top_k)
    else:
        result = _local_search(session, collection_id, query, qvec, top_k)

    trace = RAGQueryTraceRecord(
        id=_new_id("rag-trace"),
        collection_id=collection_id,
        query=query,
        mode=mode,
        embedding_model=embed_model if qvec else None,
        results_json=result,
    )
    session.add(trace)
    session.commit()

    return {"mode": mode, "trace_id": trace.id, "embedding_model": trace.embedding_model, **result}


def _chunk_payload(chunk: RAGChunkRecord, score: float) -> dict[str, Any]:
    return {
        "chunk_id": chunk.id,
        "document_id": chunk.document_id,
        "ordinal": chunk.ordinal,
        "score": round(float(score), 6),
        "excerpt": chunk.text[:_EXCERPT_CHARS],
    }


def _context_from_chunks(chunks: list[dict[str, Any]]) -> str:
    return (
        "\n\n".join(f"[chunk {c['chunk_id']}]\n{c['excerpt']}" for c in chunks)
        or "No matching context found."
    )


def _naive_search(
    session: Session,
    collection_id: str,
    query: str,
    qvec: list[float] | None,
    top_k: int,
) -> dict[str, Any]:
    chunks = list(
        session.scalars(
            select(RAGChunkRecord).where(RAGChunkRecord.collection_id == collection_id)
        ).all()
    )
    scored = sorted(
        ((_score_chunk(query, qvec, c), c) for c in chunks),
        key=lambda pair: pair[0],
        reverse=True,
    )[:top_k]
    chunk_results = [_chunk_payload(c, s) for s, c in scored]
    return {
        "chunks": chunk_results,
        "entities": [],
        "relationships": [],
        "communities": [],
        "context": _context_from_chunks(chunk_results),
    }


def _seed_entities(
    session: Session,
    collection_id: str,
    query: str,
    qvec: list[float] | None,
    limit: int,
) -> list[RAGEntityRecord]:
    entities = list(
        session.scalars(
            select(RAGEntityRecord).where(
                RAGEntityRecord.collection_id == collection_id
            )
        ).all()
    )
    query_l = query.lower()

    def score(entity: RAGEntityRecord) -> float:
        if qvec and entity.embedding_json:
            return _cosine_similarity(qvec, entity.embedding_json)
        # name mention or lexical overlap with the description
        mention = 1.0 if entity.normalized_name and entity.normalized_name in query_l else 0.0
        return mention + 0.001 * _lexical_score(query, entity.description or entity.name)

    ranked = sorted(entities, key=score, reverse=True)
    return [e for e in ranked if score(e) > 0][:limit]


def _local_search(
    session: Session,
    collection_id: str,
    query: str,
    qvec: list[float] | None,
    top_k: int,
) -> dict[str, Any]:
    seeds = _seed_entities(session, collection_id, query, qvec, limit=top_k)
    seed_ids = {e.id for e in seeds}

    # 1-hop expansion over relationships.
    rels = list(
        session.scalars(
            select(RAGRelationshipRecord).where(
                RAGRelationshipRecord.collection_id == collection_id
            )
        ).all()
    )
    neighbor_ids: set[str] = set()
    used_rels: list[RAGRelationshipRecord] = []
    for rel in rels:
        if rel.source_entity_id in seed_ids or rel.target_entity_id in seed_ids:
            used_rels.append(rel)
            neighbor_ids.add(rel.source_entity_id)
            neighbor_ids.add(rel.target_entity_id)
    all_entity_ids = seed_ids | neighbor_ids

    # chunks connected to those entities (provenance), plus top scored chunks.
    connected_chunk_ids: set[str] = set()
    if all_entity_ids:
        connected_chunk_ids = {
            row.chunk_id
            for row in session.scalars(
                select(RAGEntityChunkRecord).where(
                    RAGEntityChunkRecord.entity_id.in_(all_entity_ids)
                )
            ).all()
        }

    chunks = list(
        session.scalars(
            select(RAGChunkRecord).where(RAGChunkRecord.collection_id == collection_id)
        ).all()
    )
    scored = sorted(
        ((_score_chunk(query, qvec, c), c) for c in chunks),
        key=lambda pair: pair[0],
        reverse=True,
    )
    # Prefer graph-connected chunks, then fill with top-scored ones.
    chosen: list[tuple[float, RAGChunkRecord]] = []
    seen: set[str] = set()
    for s, c in scored:
        if c.id in connected_chunk_ids:
            chosen.append((s, c))
            seen.add(c.id)
    for s, c in scored:
        if len(chosen) >= top_k:
            break
        if c.id not in seen:
            chosen.append((s, c))
            seen.add(c.id)
    chosen = chosen[:top_k]
    chunk_results = [_chunk_payload(c, s) for s, c in chosen]

    # communities of the seed entities
    community_ids = {e.community_id for e in seeds if e.community_id}
    communities = (
        list(
            session.scalars(
                select(RAGCommunityRecord).where(
                    RAGCommunityRecord.id.in_(community_ids)
                )
            ).all()
        )
        if community_ids
        else []
    )

    entity_payload = [
        {"entity_id": e.id, "name": e.name, "type": e.type, "seed": e.id in seed_ids}
        for e in seeds
    ]
    rel_payload = [
        {
            "relationship_id": r.id,
            "source_entity_id": r.source_entity_id,
            "target_entity_id": r.target_entity_id,
            "description": r.description,
            "weight": r.weight,
        }
        for r in used_rels
    ]
    community_payload = [
        {"community_id": c.id, "title": c.title, "summary": c.summary}
        for c in communities
    ]

    context_parts = [_context_from_chunks(chunk_results)]
    if community_payload:
        context_parts.append(
            "Related community summaries:\n"
            + "\n".join(f"- {c['title']}: {c['summary']}" for c in community_payload)
        )
    return {
        "chunks": chunk_results,
        "entities": entity_payload,
        "relationships": rel_payload,
        "communities": community_payload,
        "context": "\n\n".join(context_parts),
    }


def _global_search(
    session: Session,
    collection_id: str,
    query: str,
    qvec: list[float] | None,
    top_k: int,
) -> dict[str, Any]:
    communities = list(
        session.scalars(
            select(RAGCommunityRecord).where(
                RAGCommunityRecord.collection_id == collection_id
            )
        ).all()
    )

    def score(community: RAGCommunityRecord) -> float:
        if qvec and community.summary_embedding_json:
            return _cosine_similarity(qvec, community.summary_embedding_json)
        return _lexical_score(query, f"{community.title or ''} {community.summary or ''}")

    ranked = sorted(communities, key=score, reverse=True)[:top_k]
    community_payload = [
        {
            "community_id": c.id,
            "title": c.title,
            "summary": c.summary,
            "member_count": c.member_count,
            "score": round(float(score(c)), 6),
        }
        for c in ranked
    ]
    context = (
        "\n\n".join(f"[{c['title']}]\n{c['summary']}" for c in community_payload)
        or "No community summaries available; index the collection first."
    )
    return {
        "chunks": [],
        "entities": [],
        "relationships": [],
        "communities": community_payload,
        "context": context,
    }
