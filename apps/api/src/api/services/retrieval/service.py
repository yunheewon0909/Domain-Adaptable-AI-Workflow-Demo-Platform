from __future__ import annotations

from pathlib import Path

from api.services.datasets.resolver import ResolvedDataset
from api.services.rag.embedding_client import EmbeddingClient
from api.services.rag.query import search_index
from api.services.workflows.contracts import EvidenceItem


def _derive_title(source_path: str) -> str:
    path = Path(source_path)
    stem = path.stem or path.name or source_path
    normalized = stem.replace("_", " ").replace("-", " ").strip()
    return normalized.title() or source_path


def retrieve_evidence(
    *,
    dataset: ResolvedDataset,
    query_text: str,
    top_k: int,
    embedding_client: EmbeddingClient,
) -> list[EvidenceItem]:
    hits = search_index(
        index_dir=dataset.index_dir,
        db_path=dataset.db_path,
        query_text=query_text,
        top_k=max(1, min(top_k, 8)),
        embedding_client=embedding_client,
    )
    return [
        EvidenceItem(
            chunk_id=hit.chunk_id,
            source_path=hit.source_path,
            title=_derive_title(hit.source_path),
            text=hit.text,
            score=round(hit.score, 6),
        )
        for hit in hits
    ]


def build_grounding_context(evidence: list[EvidenceItem]) -> str:
    if not evidence:
        return "No relevant evidence was retrieved."

    return "\n\n".join(
        (
            f"[{item.source_path}#{item.chunk_id}]\n"
            f"Title: {item.title}\n"
            f"Score: {item.score:.6f}\n"
            f"Text: {item.text}"
        )
        for item in evidence
    )
