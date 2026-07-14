"""Test doubles for the RAG providers, so tests stay offline."""

import uuid

import chromadb

from app.schemas.research import WebSearchFindings, WebSearchHit
from app.services.vector_store import VectorStore
from app.services.vision import VisionImage


class FakeVisionProvider:
    """Deterministic vision stand-in: a canned caption with no network call.

    Mirrors the VisionProvider protocol so captioning runs offline. Records its
    calls so a test can assert how many images were captioned.
    """

    def __init__(self, caption: str = "a fake caption") -> None:
        self.caption = caption
        self.calls: list[tuple[str, str, int]] = []

    async def answer(
        self,
        system: str,
        prompt: str,
        images: list[VisionImage],
        *,
        detail: str = "auto",
    ) -> str:
        self.calls.append((system, prompt, len(images)))
        return self.caption


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
        # Records json_mode per call so tests can assert the structured agents
        # request JSON mode while the /query path does not.
        self.json_modes: list[bool] = []

    async def generate(
        self, system: str, prompt: str, *, json_mode: bool = False
    ) -> str:
        self.calls.append((system, prompt))
        self.json_modes.append(json_mode)
        return prompt if self.echo else self.answer


class FakeSearchProvider:
    """Offline search stand-in returning canned hits and recording its calls.

    Pass error=<exc> to make every search raise it, exercising both the agent's
    degrade path (a SearchProviderError) and the must-propagate path (a
    programming error) without touching the network.
    """

    def __init__(
        self,
        hits: list[WebSearchHit] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.hits = hits if hits is not None else [_canned_hit()]
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, max_results: int) -> WebSearchFindings:
        self.calls.append((query, max_results))
        if self.error is not None:
            raise self.error
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
