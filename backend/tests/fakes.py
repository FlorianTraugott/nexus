"""Test doubles for the RAG providers, so tests stay offline."""

import uuid

import chromadb

from app.schemas.research import WebSearchFindings, WebSearchHit
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
    """Deterministic LLM stand-in that records the prompts it was given.

    With echo=True it returns the user prompt verbatim, so a test can assert
    the answer is grounded only in the chunks build_prompt was handed.
    """

    def __init__(self, answer: str = "fake answer", *, echo: bool = False) -> None:
        self.answer = answer
        self.echo = echo
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        return prompt if self.echo else self.answer


class FakeSearchProvider:
    """Offline search stand-in returning canned hits and recording its calls.

    With fail=True every search raises, to exercise the agent's degrade path
    without touching the network.
    """

    def __init__(
        self, hits: list[WebSearchHit] | None = None, *, fail: bool = False
    ) -> None:
        self.hits = hits if hits is not None else [_canned_hit()]
        self.fail = fail
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, max_results: int) -> WebSearchFindings:
        self.calls.append((query, max_results))
        if self.fail:
            raise RuntimeError("simulated provider failure")
        return WebSearchFindings(query=query, hits=self.hits)


def _canned_hit() -> WebSearchHit:
    return WebSearchHit(
        title="Example", url="https://example.com", snippet="a snippet", score=0.9
    )


def ephemeral_store() -> VectorStore:
    """An in-memory vector store wrapping a fresh Chroma collection."""
    client = chromadb.EphemeralClient()
    collection = client.create_collection(
        name=f"test-{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"}
    )
    return VectorStore(collection)
