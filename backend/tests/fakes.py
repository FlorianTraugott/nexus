"""Test doubles for the RAG providers, so tests stay offline."""

import uuid

import chromadb

from app.services.vector_store import VectorStore


class FakeEmbeddingProvider:
    """Deterministic embeddings: identical text always yields the same vector."""

    def __init__(self, dimension: int = 8) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        seed = float(len(text) % 7 + 1)
        return [seed / (i + 1) for i in range(self._dimension)]


def ephemeral_store() -> VectorStore:
    """An in-memory vector store wrapping a fresh Chroma collection."""
    client = chromadb.EphemeralClient()
    collection = client.create_collection(
        name=f"test-{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"}
    )
    return VectorStore(collection)
