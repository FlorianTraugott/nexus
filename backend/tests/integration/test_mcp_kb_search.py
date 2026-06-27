"""Tests for the MCP kb_search tool: env identity + owner-scoped retrieval.

Offline, mirroring test_retrieval.py: a deterministic MappingEmbedder, an
in-memory Chroma collection, an in-memory SQLite session, and NEXUS_MCP_USER_ID
set per test via monkeypatch. The registered tool opens a real AsyncSessionLocal,
so these drive the inner _run_kb_search with the test's injected session instead.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes import ephemeral_store

from app.agents.kb_query import run_kb_query
from app.db.models import DocumentChunk, DocumentSourceType, User
from app.db.repositories import document as document_repo
from app.mcp.server import MCPIdentityError, _run_kb_search
from app.schemas.research import KBFindings, ResearchState
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


class RecordingEmbedder:
    """Counts calls so a test can assert retrieval was never attempted."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def dimension(self) -> int:
        return 3

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[0.0, 0.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return [0.0, 0.0, 0.0]


async def _make_user(session: AsyncSession, *, is_active: bool = True) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=is_active
    )
    session.add(user)
    await session.flush()
    return user


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


async def test_returns_findings_scoped_to_configured_user(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    mine = await _make_user(db_session)
    theirs = await _make_user(db_session)
    mine_rows = await _seed(
        db_session, store, embedder, mine.id, ["alpha apple", "bravo banana"]
    )
    # The other user owns an identical "bravo banana" — it must stay invisible.
    await _seed(db_session, store, embedder, theirs.id, ["bravo banana"])
    monkeypatch.setenv("NEXUS_MCP_USER_ID", str(mine.id))

    findings = await _run_kb_search(
        db_session, "looking for bravo", embedder=embedder, store=store
    )

    assert isinstance(findings, KBFindings)
    assert findings.query == "looking for bravo"
    # Most relevant first, and only my chunks.
    assert findings.findings[0].content_preview == "bravo banana"
    my_ids = {row.id for row in mine_rows}
    assert all(f.chunk_id in my_ids for f in findings.findings)
    assert len(findings.findings) == 2


async def test_other_users_corpus_is_invisible(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    mine = await _make_user(db_session)
    theirs = await _make_user(db_session)
    # Only the other user has any indexed chunks; owner-scoping yields nothing.
    await _seed(db_session, store, embedder, theirs.id, ["bravo banana"])
    monkeypatch.setenv("NEXUS_MCP_USER_ID", str(mine.id))

    findings = await _run_kb_search(
        db_session, "looking for bravo", embedder=embedder, store=store
    )

    assert findings.findings == []


async def test_unset_env_raises_and_does_not_retrieve(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXUS_MCP_USER_ID", raising=False)
    embedder, store = RecordingEmbedder(), ephemeral_store()

    with pytest.raises(MCPIdentityError):
        await _run_kb_search(db_session, "q", embedder=embedder, store=store)

    assert embedder.calls == 0


async def test_malformed_uuid_raises_and_does_not_retrieve(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEXUS_MCP_USER_ID", "not-a-uuid")
    embedder, store = RecordingEmbedder(), ephemeral_store()

    with pytest.raises(MCPIdentityError):
        await _run_kb_search(db_session, "q", embedder=embedder, store=store)

    assert embedder.calls == 0


async def test_unknown_user_raises_and_does_not_retrieve(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A well-formed id that matches no row.
    monkeypatch.setenv("NEXUS_MCP_USER_ID", str(uuid.uuid4()))
    embedder, store = RecordingEmbedder(), ephemeral_store()

    with pytest.raises(MCPIdentityError):
        await _run_kb_search(db_session, "q", embedder=embedder, store=store)

    assert embedder.calls == 0


async def test_inactive_user_raises_and_does_not_retrieve(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _make_user(db_session, is_active=False)
    monkeypatch.setenv("NEXUS_MCP_USER_ID", str(user.id))
    embedder, store = RecordingEmbedder(), ephemeral_store()

    with pytest.raises(MCPIdentityError):
        await _run_kb_search(db_session, "q", embedder=embedder, store=store)

    assert embedder.calls == 0


async def test_agent_and_tool_produce_identical_findings(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The shared to_finding lift must not change behavior: same data, same user,
    # both callers, identical findings.
    embedder, store = MappingEmbedder(), ephemeral_store()
    user = await _make_user(db_session)
    await _seed(db_session, store, embedder, user.id, ["alpha apple", "bravo banana"])
    monkeypatch.setenv("NEXUS_MCP_USER_ID", str(user.id))

    state = await run_kb_query(
        ResearchState(topic="looking for bravo", user_id=user.id, k=5),
        db_session,
        embedder=embedder,
        store=store,
    )
    findings = await _run_kb_search(
        db_session, "looking for bravo", 5, embedder=embedder, store=store
    )

    assert state.kb is not None
    assert findings.query == state.kb.query
    assert findings.findings == state.kb.findings
