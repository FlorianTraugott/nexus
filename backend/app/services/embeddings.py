"""Embedding providers: turn text into vectors for semantic search.

The rest of the RAG pipeline depends only on the EmbeddingProvider protocol,
so the concrete backend (OpenAI today) can be swapped without touching callers.
"""

from functools import lru_cache
from typing import Protocol

from openai import AsyncOpenAI

from app.core.config import get_settings


class EmbeddingProvider(Protocol):
    """Turns text into fixed-length vectors."""

    @property
    def dimension(self) -> int:
        """Length of every vector this provider returns."""
        ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents, preserving input order."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        ...


class OpenAIEmbeddingProvider:
    """Embeddings backed by OpenAI's text-embedding-3 models."""

    def __init__(self, api_key: str, model: str, dimensions: int) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._dimension = dimensions

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # Skip the network round-trip on empty input; the API would reject it.
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=self._model, input=texts, dimensions=self._dimension
        )
        return [item.embedding for item in response.data]

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_texts([text])
        return vectors[0]


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """Build the configured provider once and reuse it across requests."""
    settings = get_settings()
    if settings.EMBEDDING_PROVIDER == "openai":
        return OpenAIEmbeddingProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.EMBEDDING_MODEL,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
    raise ValueError(f"Unknown embedding provider: {settings.EMBEDDING_PROVIDER!r}")
