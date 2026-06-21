"""Tests for the ChromaDB vector store wrapper."""

import uuid

import chromadb
import pytest

from app.services.vector_store import VectorStore

# Three orthogonal unit vectors so cosine distance ordering is unambiguous.
_IDS = ["c1", "c2", "c3"]
_EMBEDDINGS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
_DOCUMENTS = ["alpha", "beta", "gamma"]
_METADATAS = [
    {"document_id": "d1"},
    {"document_id": "d1"},
    {"document_id": "d2"},
]


@pytest.fixture
def store() -> VectorStore:
    # Ephemeral client = in-memory, no disk or network. Unique name per test.
    client = chromadb.EphemeralClient()
    collection = client.create_collection(
        name=f"test-{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"}
    )
    return VectorStore(collection)


def _seed(store: VectorStore) -> None:
    store.add(
        ids=_IDS, embeddings=_EMBEDDINGS, documents=_DOCUMENTS, metadatas=_METADATAS
    )


def test_query_returns_nearest_first(store: VectorStore) -> None:
    _seed(store)
    matches = store.query([0.9, 0.1, 0.0], k=2)

    assert [m.id for m in matches] == ["c1", "c2"]
    assert matches[0].document == "alpha"
    assert matches[0].metadata["document_id"] == "d1"
    assert matches[0].distance < matches[1].distance


def test_query_respects_where_filter(store: VectorStore) -> None:
    _seed(store)
    matches = store.query([0.9, 0.1, 0.0], k=5, where={"document_id": "d2"})

    assert [m.id for m in matches] == ["c3"]


def test_delete_by_document_removes_only_that_document(store: VectorStore) -> None:
    _seed(store)
    assert store.count() == 3

    store.delete_by_document("d1")

    assert store.count() == 1
    remaining = store.query([0.0, 0.0, 1.0], k=5)
    assert [m.id for m in remaining] == ["c3"]


def test_add_empty_is_noop(store: VectorStore) -> None:
    store.add(ids=[], embeddings=[], documents=[], metadatas=[])
    assert store.count() == 0


def test_add_upsert_is_idempotent(store: VectorStore) -> None:
    _seed(store)
    _seed(store)
    assert store.count() == 3
