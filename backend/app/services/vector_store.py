"""Vector store over ChromaDB: persist chunk vectors and search them.

A thin synchronous wrapper around a single Chroma collection. Chroma's client
is sync, so callers in the async pipeline offload these calls to a thread
(`asyncio.to_thread`), mirroring how parsing and image extraction already run.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

import chromadb
from chromadb.api.types import Embeddings, Metadatas

from app.core.config import get_settings


@dataclass(frozen=True)
class VectorMatch:
    """One search hit: the chunk id, its text, metadata, and distance."""

    id: str
    document: str
    metadata: dict[str, Any]
    distance: float


class VectorStore:
    """Thin synchronous wrapper around a Chroma collection."""

    def __init__(self, collection: chromadb.Collection) -> None:
        self._collection = collection

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Upsert chunk vectors. Upsert keeps re-indexing idempotent."""
        if not ids:
            return
        # Chroma's param types are invariant (numpy-oriented); our plain
        # list[list[float]] / list[dict] are accepted at runtime.
        self._collection.upsert(
            ids=ids,
            embeddings=cast(Embeddings, embeddings),
            documents=documents,
            metadatas=cast(Metadatas, metadatas),
        )

    def query(
        self,
        embedding: list[float],
        k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        """Return the k nearest chunks, optionally filtered by metadata."""
        result = self._collection.query(
            query_embeddings=cast(Embeddings, [embedding]),
            n_results=k,
            where=where,
        )
        # Chroma nests each field one level deep (one list per query embedding)
        # and types them as optional; `or [[]]` keeps the indexing total.
        ids = (result["ids"] or [[]])[0]
        documents = (result["documents"] or [[]])[0]
        metadatas = (result["metadatas"] or [[]])[0]
        distances = (result["distances"] or [[]])[0]
        return [
            VectorMatch(
                id=id_, document=doc, metadata=dict(meta) if meta else {}, distance=dist
            )
            for id_, doc, meta, dist in zip(
                ids, documents, metadatas, distances, strict=True
            )
        ]

    def delete_by_document(self, document_id: Any) -> None:
        """Remove every vector belonging to a document."""
        self._collection.delete(where={"document_id": str(document_id)})

    def count(self) -> int:
        """Number of vectors currently stored."""
        return self._collection.count()


@lru_cache
def get_vector_store() -> VectorStore:
    """Build the persistent store once and reuse it across requests."""
    settings = get_settings()
    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    collection = client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    return VectorStore(collection)
