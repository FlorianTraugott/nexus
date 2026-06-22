"""Retrieval: turn a question into the owner's most relevant chunks."""

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import DocumentChunk
from app.db.repositories import document as document_repo
from app.services.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.vector_store import VectorStore, get_vector_store


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: DocumentChunk
    # Chroma cosine distance: LOWER is more relevant, not a similarity score.
    distance: float


async def retrieve(
    session: AsyncSession,
    query: str,
    user_id: uuid.UUID,
    k: int | None = None,
    embedder: EmbeddingProvider | None = None,
    store: VectorStore | None = None,
) -> list[RetrievedChunk]:
    """Embed the query, search the user's vectors, and hydrate DB rows."""
    k = k if k is not None else get_settings().RAG_TOP_K
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    # Resolve providers lazily so callers (and tests) can inject fakes.
    embedder = embedder or get_embedding_provider()
    store = store or get_vector_store()

    query_vector = await embedder.embed_query(query)
    matches = await asyncio.to_thread(
        store.query, query_vector, k, {"user_id": str(user_id)}
    )
    if not matches:
        return []

    ordered_ids = [uuid.UUID(match.id) for match in matches]
    rows = await document_repo.get_chunks_by_ids(session, ordered_ids)
    by_id = {row.id: row for row in rows}

    # The DB row is the source of truth; re-sort into the vector store's
    # relevance order and skip ids whose row was deleted after indexing.
    return [
        RetrievedChunk(chunk=by_id[id_], distance=match.distance)
        for id_, match in zip(ordered_ids, matches, strict=True)
        if id_ in by_id
    ]
