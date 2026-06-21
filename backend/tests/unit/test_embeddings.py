"""Tests for the embedding provider abstraction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import embeddings
from app.services.embeddings import OpenAIEmbeddingProvider, get_embedding_provider


def _fake_response(vectors: list[list[float]]) -> SimpleNamespace:
    """Mimic the shape of an OpenAI embeddings response."""
    return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in vectors])


@pytest.fixture
def provider() -> OpenAIEmbeddingProvider:
    p = OpenAIEmbeddingProvider(api_key="test-key", model="test-model", dimensions=4)
    p._client = AsyncMock()
    return p


async def test_embed_texts_returns_vectors_in_order(
    provider: OpenAIEmbeddingProvider,
) -> None:
    provider._client.embeddings.create = AsyncMock(
        return_value=_fake_response([[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]])
    )
    result = await provider.embed_texts(["alpha", "beta"])

    assert result == [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]
    assert all(len(v) == provider.dimension for v in result)
    provider._client.embeddings.create.assert_awaited_once_with(
        model="test-model", input=["alpha", "beta"], dimensions=4
    )


async def test_embed_texts_empty_skips_api_call(
    provider: OpenAIEmbeddingProvider,
) -> None:
    provider._client.embeddings.create = AsyncMock()
    assert await provider.embed_texts([]) == []
    provider._client.embeddings.create.assert_not_awaited()


async def test_embed_query_returns_single_vector(
    provider: OpenAIEmbeddingProvider,
) -> None:
    provider._client.embeddings.create = AsyncMock(
        return_value=_fake_response([[1.0, 2.0, 3.0, 4.0]])
    )
    vector = await provider.embed_query("a question")

    assert vector == [1.0, 2.0, 3.0, 4.0]
    assert len(vector) == provider.dimension


def test_factory_builds_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    get_embedding_provider.cache_clear()
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(
            EMBEDDING_PROVIDER="openai",
            OPENAI_API_KEY="test-key",
            EMBEDDING_MODEL="text-embedding-3-small",
            EMBEDDING_DIMENSIONS=1536,
        ),
    )

    built = get_embedding_provider()
    assert isinstance(built, OpenAIEmbeddingProvider)
    assert built.dimension == 1536
    get_embedding_provider.cache_clear()


def test_factory_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    get_embedding_provider.cache_clear()
    monkeypatch.setattr(
        embeddings,
        "get_settings",
        lambda: SimpleNamespace(
            EMBEDDING_PROVIDER="bogus",
            OPENAI_API_KEY="test-key",
            EMBEDDING_MODEL="m",
            EMBEDDING_DIMENSIONS=4,
        ),
    )

    with pytest.raises(ValueError, match="bogus"):
        get_embedding_provider()
    get_embedding_provider.cache_clear()
