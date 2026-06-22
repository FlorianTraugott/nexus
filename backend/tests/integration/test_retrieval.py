"""Tests for the retrieval service."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes import ephemeral_store

from app.db.models import DocumentChunk, DocumentSourceType, User
from app.db.repositories import document as document_repo
from app.services.retrieval import retrieve
from app.services.vector_store import VectorStore

# Orthogonal vectors so cosine ordering is unambiguous.
_CONTENTS = ["alpha apple", "bravo banana", "charlie cherry"]
_VECTORS = {
    "alpha apple": [1.0, 0.0, 0.0],
    "bravo banana": [0.0, 1.0, 0.0],
    "charlie cherry": [0.0, 0.0, 1.0],
    "looking for bravo": [0.0, 1.0, 0.0],
}


class MappingEmbedder:
    """Returns a fixed vector per known string; zeros for anything else."""

    def __init__(self, dimension: int = 3) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        return _VECTORS.get(text, [0.0] * self._dimension)


async def _seed(
    session: AsyncSession,
    store: VectorStore,
    embedder: MappingEmbedder,
    user_id: uuid.UUID,
    contents: list[str],
) -> list[DocumentChunk]:
    """Create a document with chunks and index their vectors for one user."""
    document = await document_repo.create_document(
        session, user_id, "doc.pdf", DocumentSourceType.PDF
    )
    rows = await document_repo.replace_chunks(session, document.id, contents)
    await session.commit()

    vectors = await embedder.embed_texts([row.content for row in rows])
    store.add(
        ids=[str(row.id) for row in rows],
        embeddings=vectors,
        documents=[row.content for row in rows],
        metadatas=[
            {
                "document_id": str(document.id),
                "user_id": str(user_id),
                "chunk_index": row.chunk_index,
            }
            for row in rows
        ],
    )
    return rows


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    return user.id


async def test_retrieve_orders_by_relevance(db_session: AsyncSession) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    user_id = await _make_user(db_session)
    await _seed(db_session, store, embedder, user_id, _CONTENTS)

    results = await retrieve(
        db_session, "looking for bravo", user_id, k=3, embedder=embedder, store=store
    )

    assert [r.chunk.content for r in results][0] == "bravo banana"
    distances = [r.distance for r in results]
    assert distances == sorted(distances)  # most relevant (lowest) first


async def test_retrieve_uses_db_content_not_vector_copy(
    db_session: AsyncSession,
) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    user_id = await _make_user(db_session)
    rows = await _seed(db_session, store, embedder, user_id, _CONTENTS)

    # Change the DB row after indexing; the vector store still holds the old text.
    bravo = await db_session.get(DocumentChunk, rows[1].id)
    assert bravo is not None
    bravo.content = "DB AUTHORITATIVE BRAVO"
    await db_session.commit()

    results = await retrieve(
        db_session, "looking for bravo", user_id, k=3, embedder=embedder, store=store
    )

    assert results[0].chunk.content == "DB AUTHORITATIVE BRAVO"


async def test_retrieve_skips_ids_with_no_db_row(db_session: AsyncSession) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    user_id = await _make_user(db_session)
    rows = await _seed(db_session, store, embedder, user_id, _CONTENTS)

    # Delete one row but leave its vector indexed.
    charlie = await db_session.get(DocumentChunk, rows[2].id)
    assert charlie is not None
    await db_session.delete(charlie)
    await db_session.commit()

    results = await retrieve(
        db_session, "charlie cherry", user_id, k=3, embedder=embedder, store=store
    )

    contents = [r.chunk.content for r in results]
    assert "charlie cherry" not in contents
    assert len(results) == 2


async def test_retrieve_is_scoped_to_user(db_session: AsyncSession) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    mine = await _make_user(db_session)
    theirs = await _make_user(db_session)
    await _seed(db_session, store, embedder, mine, ["alpha apple"])
    await _seed(db_session, store, embedder, theirs, ["bravo banana"])

    results = await retrieve(
        db_session, "looking for bravo", mine, k=5, embedder=embedder, store=store
    )

    assert [r.chunk.content for r in results] == ["alpha apple"]


async def test_retrieve_rejects_non_positive_k(db_session: AsyncSession) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    user_id = await _make_user(db_session)

    with pytest.raises(ValueError, match="k must be positive"):
        await retrieve(db_session, "q", user_id, k=0, embedder=embedder, store=store)
