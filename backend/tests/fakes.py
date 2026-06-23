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


class FakeGenerationProvider:
    """Deterministic LLM stand-in that records the prompts it was given."""

    def __init__(self, answer: str = "fake answer") -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        return self.answer


def ephemeral_store() -> VectorStore:
    """An in-memory vector store wrapping a fresh Chroma collection."""
    client = chromadb.EphemeralClient()
    collection = client.create_collection(
        name=f"test-{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"}
    )
    return VectorStore(collection)
