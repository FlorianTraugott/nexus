"""Tests for the query endpoint (retrieval + generation), kept offline."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from tests.fakes import FakeGenerationProvider, ephemeral_store

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import DocumentSourceType, MessageRole, User
from app.db.repositories import conversation as conversation_repo
from app.db.repositories import document as document_repo
from app.db.session import get_db
from app.main import app
from app.services.embeddings import get_embedding_provider
from app.services.generation import get_generation_provider
from app.services.vector_store import VectorStore, get_vector_store

QUERY = "/api/v1/query"

# Orthogonal vectors so cosine ordering is unambiguous.
_VECTORS = {
    "alpha apple": [1.0, 0.0, 0.0],
    "bravo banana": [0.0, 1.0, 0.0],
    "charlie cherry": [0.0, 0.0, 1.0],
    "find bravo": [0.0, 1.0, 0.0],
    # A distinct chunk that also matches "find bravo" (distance 0), so the
    # scoping test can retrieve the owner's chunk within the abstention gate.
    "bravo mine": [0.0, 1.0, 0.0],
}


class MappingEmbedder:
    """Fixed vector per known string; zeros for anything else."""

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


@dataclass
class _Env:
    client: AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    store: VectorStore
    embedder: MappingEmbedder
    generator: FakeGenerationProvider


@pytest_asyncio.fixture
async def env() -> AsyncIterator[_Env]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    store = ephemeral_store()
    embedder = MappingEmbedder()
    generator = FakeGenerationProvider(echo=True)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_embedding_provider] = lambda: embedder
    app.dependency_overrides[get_generation_provider] = lambda: generator

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield _Env(client, session_factory, store, embedder, generator)

    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed_user_chunks(env: _Env, contents: list[str]) -> uuid.UUID:
    """Create a user, index their chunks into DB + store, return the user id."""
    async with env.session_factory() as session:
        user = User(
            email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True
        )
        session.add(user)
        await session.flush()
        user_id = user.id
        document = await document_repo.create_document(
            session, user_id, "doc.pdf", DocumentSourceType.PDF
        )
        rows = await document_repo.replace_chunks(session, document.id, contents)
        await session.commit()

        vectors = await env.embedder.embed_texts(contents)
        env.store.add(
            ids=[str(row.id) for row in rows],
            embeddings=vectors,
            documents=contents,
            metadatas=[
                {
                    "document_id": str(document.id),
                    "user_id": str(user_id),
                    "chunk_index": row.chunk_index,
                }
                for row in rows
            ],
        )
    return user_id


async def _seed_conversation(
    env: _Env, user_id: uuid.UUID, turns: list[tuple[str, str]]
) -> uuid.UUID:
    """Create a conversation owned by user_id, seeded with prior (role, content)."""
    async with env.session_factory() as session:
        conversation = await conversation_repo.create_conversation(session, user_id)
        for role, content in turns:
            await conversation_repo.add_message(
                session, conversation.id, MessageRole(role), content
            )
        await session.commit()
        return conversation.id


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


async def test_query_returns_answer_and_citations(env: _Env) -> None:
    user_id = await _seed_user_chunks(
        env, ["alpha apple", "bravo banana", "charlie cherry"]
    )

    response = await env.client.post(
        QUERY, json={"question": "find bravo", "k": 3}, headers=_auth(user_id)
    )

    assert response.status_code == 200
    body = response.json()
    assert "bravo banana" in body["answer"]  # echoing fake returns the prompt
    previews = [c["content_preview"] for c in body["citations"]]
    assert previews[0] == "bravo banana"  # most relevant first
    distances = [c["distance"] for c in body["citations"]]
    assert distances == sorted(distances)  # lowest distance first
    assert set(previews) == {"alpha apple", "bravo banana", "charlie cherry"}
    assert env.generator.json_modes == [False]  # query is non-structured


async def test_query_requires_authentication(env: _Env) -> None:
    response = await env.client.post(QUERY, json={"question": "find bravo"})
    assert response.status_code in (401, 403)


async def test_query_is_scoped_to_user(env: _Env) -> None:
    mine = await _seed_user_chunks(env, ["bravo mine"])
    await _seed_user_chunks(env, ["bravo banana"])  # another user's matching chunk

    response = await env.client.post(
        QUERY, json={"question": "find bravo", "k": 5}, headers=_auth(mine)
    )

    assert response.status_code == 200
    body = response.json()
    # The query matches BOTH users' chunks equally (distance 0), yet only the
    # owner's chunk is retrievable — the other user's "bravo banana" is scoped
    # out entirely, so it appears in neither the citations nor the answer.
    assert {c["content_preview"] for c in body["citations"]} == {"bravo mine"}
    assert "bravo banana" not in body["answer"]


async def test_query_abstains_when_best_match_is_too_far(env: _Env) -> None:
    # The only chunk is orthogonal to the query (cosine distance 1.0 > the 0.5
    # gate), so the endpoint abstains without calling the generator.
    user_id = await _seed_user_chunks(env, ["alpha apple"])

    response = await env.client.post(
        QUERY, json={"question": "find bravo", "k": 5}, headers=_auth(user_id)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["citations"] == []
    assert "could not find anything relevant" in body["answer"].lower()
    assert env.generator.calls == []  # generator was never invoked


async def test_query_answer_is_grounded_in_cited_chunks(env: _Env) -> None:
    user_id = await _seed_user_chunks(
        env, ["alpha apple", "bravo banana", "charlie cherry"]
    )

    response = await env.client.post(
        QUERY, json={"question": "find bravo", "k": 1}, headers=_auth(user_id)
    )

    body = response.json()
    # Only the single most relevant chunk is retrieved, cited, and seen by the LLM.
    assert [c["content_preview"] for c in body["citations"]] == ["bravo banana"]
    assert "bravo banana" in body["answer"]
    assert "alpha apple" not in body["answer"]
    assert "charlie cherry" not in body["answer"]


async def test_query_passes_conversation_history_to_generation(env: _Env) -> None:
    user_id = await _seed_user_chunks(env, ["bravo banana"])
    conversation_id = await _seed_conversation(
        env,
        user_id,
        [("user", "tell me about bravo"), ("assistant", "bravo is a fruit")],
    )
    # A non-echo generator: rewrite_query returns "find bravo" (which the mapping
    # embedder matches to the seeded chunk, so retrieval succeeds), and the same
    # value is the answer. We inspect the recorded generation prompt directly.
    generator = FakeGenerationProvider(answer="find bravo")
    app.dependency_overrides[get_generation_provider] = lambda: generator

    response = await env.client.post(
        QUERY,
        json={
            "question": "what about it?",
            "conversation_id": str(conversation_id),
            "k": 1,
        },
        headers=_auth(user_id),
    )

    assert response.status_code == 200
    # rewrite runs first, generation last; the generation call carries the history.
    gen_system, gen_prompt = generator.calls[-1]
    assert "Previous conversation:" in gen_prompt
    assert "user: tell me about bravo" in gen_prompt
    assert "assistant: bravo is a fruit" in gen_prompt
    assert "Question: what about it?" in gen_prompt  # the ORIGINAL question
    assert "never from the conversation" in gen_system  # framing clause present


async def test_query_without_conversation_passes_no_history(env: _Env) -> None:
    # No conversation_id: the generation prompt must be exactly today's, with no
    # history block and no framing clause, so the eval baselines stay comparable.
    user_id = await _seed_user_chunks(env, ["bravo banana"])

    response = await env.client.post(
        QUERY, json={"question": "find bravo", "k": 1}, headers=_auth(user_id)
    )

    assert response.status_code == 200
    gen_system, gen_prompt = env.generator.calls[-1]
    assert "Previous conversation:" not in gen_prompt
    assert "conversation" not in gen_system


async def test_query_rejects_k_above_max(env: _Env) -> None:
    user_id = await _seed_user_chunks(env, ["alpha apple"])

    response = await env.client.post(
        QUERY, json={"question": "find bravo", "k": 9999}, headers=_auth(user_id)
    )

    assert response.status_code == 422
