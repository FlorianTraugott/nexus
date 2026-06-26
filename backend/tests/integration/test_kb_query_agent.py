"""Tests for the KB-query agent: owner-scoped retrieval into ResearchState.

Offline: a deterministic MappingEmbedder and an in-memory Chroma collection, so
no network or real provider is involved (mirrors test_retrieval.py).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes import ephemeral_store

from app.agents.kb_query import run_kb_query
from app.db.models import DocumentChunk, DocumentSourceType, User
from app.db.repositories import document as document_repo
from app.schemas.research import ResearchStage, ResearchState
from app.services.vector_store import VectorStore

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


class BoomEmbedder:
    """Raises on use, to prove a retrieval failure propagates (not swallowed)."""

    @property
    def dimension(self) -> int:
        return 3

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedder down")

    async def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("embedder down")


async def _make_user(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    return user.id


async def _seed(
    session: AsyncSession,
    store: VectorStore,
    embedder: MappingEmbedder,
    user_id: uuid.UUID,
    contents: list[str],
) -> list[DocumentChunk]:
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


def _state(user_id: uuid.UUID, *, k: int | None = 5) -> ResearchState:
    return ResearchState(topic="looking for bravo", user_id=user_id, k=k)


async def test_normal_path_populates_kb_user_scoped(db_session: AsyncSession) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    mine = await _make_user(db_session)
    theirs = await _make_user(db_session)
    mine_rows = await _seed(
        db_session, store, embedder, mine, ["alpha apple", "bravo banana"]
    )
    await _seed(db_session, store, embedder, theirs, ["bravo banana"])

    result = await run_kb_query(
        _state(mine), db_session, embedder=embedder, store=store
    )

    assert result.kb is not None
    assert result.kb.query == "looking for bravo"
    # Most relevant first, and only my chunks — the other user's bravo is excluded.
    assert result.kb.findings[0].content_preview == "bravo banana"
    my_ids = {row.id for row in mine_rows}
    assert all(f.chunk_id in my_ids for f in result.kb.findings)
    assert len(result.kb.findings) == 2
    assert result.stage is ResearchStage.SUMMARISE
    assert result.warnings == []
    assert result.error is None


async def test_empty_retrieval_is_normal_not_error(db_session: AsyncSession) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    mine = await _make_user(db_session)
    theirs = await _make_user(db_session)
    # Only the other user has any indexed chunks; owner-scoping yields nothing.
    await _seed(db_session, store, embedder, theirs, ["bravo banana"])

    result = await run_kb_query(
        _state(mine), db_session, embedder=embedder, store=store
    )

    assert result.kb is not None
    assert result.kb.query == "looking for bravo"
    assert result.kb.findings == []
    assert result.stage is ResearchStage.SUMMARISE
    assert result.warnings == []
    assert result.error is None  # empty corpus match is normal, not a failure


async def test_retrieval_failure_propagates(db_session: AsyncSession) -> None:
    state = _state(await _make_user(db_session))

    # A genuine failure must surface so orchestration can set state.error;
    # the agent does not swallow it into empty findings.
    with pytest.raises(RuntimeError, match="embedder down"):
        await run_kb_query(
            state, db_session, embedder=BoomEmbedder(), store=ephemeral_store()
        )

    assert state.kb is None
    assert state.warnings == []
    assert state.error is None
