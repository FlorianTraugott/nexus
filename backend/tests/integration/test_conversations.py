"""Tests for conversation CRUD and /query turn persistence, kept offline.

Reuses the query harness: in-memory SQLite, an ephemeral Chroma store, and
provider factories overridden with offline fakes.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
from app.db.models import Conversation, DocumentSourceType, User
from app.db.repositories import document as document_repo
from app.db.session import get_db
from app.main import app
from app.services.embeddings import get_embedding_provider
from app.services.generation import get_generation_provider
from app.services.vector_store import VectorStore, get_vector_store

CONV = "/api/v1/conversations"
QUERY = "/api/v1/query"

# Orthogonal vectors so cosine ordering is unambiguous.
_VECTORS = {
    "alpha apple": [1.0, 0.0, 0.0],
    "bravo banana": [0.0, 1.0, 0.0],
    "charlie cherry": [0.0, 0.0, 1.0],
    "find bravo": [0.0, 1.0, 0.0],
    # A follow-up that embeds orthogonal to "bravo banana" (distance 1.0 > the 0.5
    # gate): retrieval abstains UNLESS the rewrite turns it into "find bravo".
    "second one": [0.0, 0.0, 1.0],
}


class _RewriteThenAnswerGenerator:
    """Branches on the system prompt: rewrite calls return a controlled standalone
    question; answer calls return a fixed answer. Records both so a test can tell
    whether the rewrite step fired."""

    def __init__(self, *, rewritten: str = "find bravo", answer: str = "ANSWER"):
        self.rewritten = rewritten
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    async def generate(
        self, system: str, prompt: str, *, json_mode: bool = False
    ) -> str:
        self.calls.append((system, prompt))
        if "rewrite" in system.lower():
            return self.rewritten
        return self.answer

    @property
    def rewrite_calls(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if "rewrite" in c[0].lower()]


class _RewriteFailsGenerator:
    """Raises on the rewrite call (to exercise best-effort degrade) but answers
    normally, so a failed rewrite must not fail the request."""

    def __init__(self, *, answer: str = "ANSWER"):
        self.answer = answer

    async def generate(
        self, system: str, prompt: str, *, json_mode: bool = False
    ) -> str:
        if "rewrite" in system.lower():
            raise RuntimeError("rewrite boom")
        return self.answer


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


async def _create_user(env: _Env) -> uuid.UUID:
    async with env.session_factory() as session:
        user = User(
            email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True
        )
        session.add(user)
        await session.commit()
        return user.id


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


async def _make_conversation(
    env: _Env, user_id: uuid.UUID, title: str, created_at: datetime
) -> uuid.UUID:
    """Insert a conversation with an explicit created_at (deterministic order)."""
    async with env.session_factory() as session:
        conversation = Conversation(user_id=user_id, title=title, created_at=created_at)
        session.add(conversation)
        await session.commit()
        return conversation.id


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


async def test_create_conversation_with_title(env: _Env) -> None:
    user_id = await _create_user(env)

    response = await env.client.post(
        CONV, json={"title": "My chat"}, headers=_auth(user_id)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "My chat"
    assert uuid.UUID(body["id"])


async def test_create_conversation_defaults_title(env: _Env) -> None:
    user_id = await _create_user(env)

    response = await env.client.post(CONV, json={}, headers=_auth(user_id))

    assert response.status_code == 201
    assert response.json()["title"] == "New conversation"


async def test_get_conversation_starts_empty(env: _Env) -> None:
    user_id = await _create_user(env)
    created = await env.client.post(CONV, json={}, headers=_auth(user_id))
    conversation_id = created.json()["id"]

    response = await env.client.get(f"{CONV}/{conversation_id}", headers=_auth(user_id))

    assert response.status_code == 200
    assert response.json()["messages"] == []


async def test_list_conversations_newest_first(env: _Env) -> None:
    user_id = await _create_user(env)
    now = datetime.now(UTC)
    older = await _make_conversation(env, user_id, "older", now - timedelta(hours=1))
    newer = await _make_conversation(env, user_id, "newer", now)

    response = await env.client.get(CONV, headers=_auth(user_id))

    assert response.status_code == 200
    ids = [c["id"] for c in response.json()]
    assert ids == [str(newer), str(older)]


async def test_list_conversations_scoped_to_user(env: _Env) -> None:
    mine = await _create_user(env)
    other = await _create_user(env)
    await env.client.post(CONV, json={"title": "mine"}, headers=_auth(mine))
    await env.client.post(CONV, json={"title": "theirs"}, headers=_auth(other))

    response = await env.client.get(CONV, headers=_auth(mine))

    titles = [c["title"] for c in response.json()]
    assert titles == ["mine"]


async def test_get_conversation_of_another_user_404s(env: _Env) -> None:
    mine = await _create_user(env)
    other = await _create_user(env)
    created = await env.client.post(CONV, json={}, headers=_auth(mine))
    conversation_id = created.json()["id"]

    response = await env.client.get(f"{CONV}/{conversation_id}", headers=_auth(other))

    # 404 (not 403) so a probe can't tell a foreign conversation from a missing one.
    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found"


async def test_delete_conversation(env: _Env) -> None:
    user_id = await _create_user(env)
    created = await env.client.post(CONV, json={}, headers=_auth(user_id))
    conversation_id = created.json()["id"]

    deleted = await env.client.delete(
        f"{CONV}/{conversation_id}", headers=_auth(user_id)
    )
    assert deleted.status_code == 204

    gone = await env.client.get(f"{CONV}/{conversation_id}", headers=_auth(user_id))
    assert gone.status_code == 404


async def test_delete_conversation_of_another_user_404s(env: _Env) -> None:
    mine = await _create_user(env)
    other = await _create_user(env)
    created = await env.client.post(CONV, json={}, headers=_auth(mine))
    conversation_id = created.json()["id"]

    response = await env.client.delete(
        f"{CONV}/{conversation_id}", headers=_auth(other)
    )
    assert response.status_code == 404


async def test_query_with_conversation_persists_turn_in_order(env: _Env) -> None:
    user_id = await _seed_user_chunks(
        env, ["alpha apple", "bravo banana", "charlie cherry"]
    )
    created = await env.client.post(CONV, json={}, headers=_auth(user_id))
    conversation_id = created.json()["id"]

    query = await env.client.post(
        QUERY,
        json={"question": "find bravo", "k": 3, "conversation_id": conversation_id},
        headers=_auth(user_id),
    )
    assert query.status_code == 200
    answer = query.json()["answer"]

    detail = await env.client.get(f"{CONV}/{conversation_id}", headers=_auth(user_id))
    messages = detail.json()["messages"]

    # Exactly two messages, user BEFORE assistant, positions consecutive.
    assert [m["position"] for m in messages] == [0, 1]
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "find bravo"
    assert messages[0]["citations"] is None
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == answer
    # The assistant turn carries its citations as stored JSON.
    previews = [c["content_preview"] for c in messages[1]["citations"]]
    assert "bravo banana" in previews


async def test_query_without_conversation_persists_nothing(env: _Env) -> None:
    user_id = await _seed_user_chunks(env, ["bravo banana"])
    created = await env.client.post(CONV, json={}, headers=_auth(user_id))
    conversation_id = created.json()["id"]

    # No conversation_id on the query -> stateless, today's behaviour.
    query = await env.client.post(
        QUERY, json={"question": "find bravo", "k": 3}, headers=_auth(user_id)
    )
    assert query.status_code == 200

    detail = await env.client.get(f"{CONV}/{conversation_id}", headers=_auth(user_id))
    assert detail.json()["messages"] == []


async def test_query_abstention_persists_its_turn(env: _Env) -> None:
    # Orthogonal chunk -> distance 1.0 > 0.5 gate -> abstain, no generation call.
    user_id = await _seed_user_chunks(env, ["alpha apple"])
    created = await env.client.post(CONV, json={}, headers=_auth(user_id))
    conversation_id = created.json()["id"]

    query = await env.client.post(
        QUERY,
        json={"question": "find bravo", "k": 5, "conversation_id": conversation_id},
        headers=_auth(user_id),
    )
    assert query.status_code == 200
    assert env.generator.calls == []  # abstained without generating

    detail = await env.client.get(f"{CONV}/{conversation_id}", headers=_auth(user_id))
    messages = detail.json()["messages"]

    # The abstention is a real turn: it is recorded, and the transcript is honest.
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "could not find anything relevant" in messages[1]["content"].lower()
    assert messages[1]["citations"] == []  # empty, not null — a turn with no sources


async def test_query_bad_conversation_id_404s_before_generating(env: _Env) -> None:
    user_id = await _seed_user_chunks(env, ["bravo banana"])

    response = await env.client.post(
        QUERY,
        json={
            "question": "find bravo",
            "k": 3,
            "conversation_id": str(uuid.uuid4()),  # not the caller's / nonexistent
        },
        headers=_auth(user_id),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found"
    assert env.generator.calls == []  # ownership checked before any generation


async def test_rewrite_skipped_on_empty_history(env: _Env) -> None:
    stub = _RewriteThenAnswerGenerator()
    app.dependency_overrides[get_generation_provider] = lambda: stub
    user_id = await _seed_user_chunks(env, ["bravo banana"])
    created = await env.client.post(CONV, json={}, headers=_auth(user_id))
    conversation_id = created.json()["id"]

    # First turn: the conversation has no messages yet, so no rewrite step runs.
    response = await env.client.post(
        QUERY,
        json={"question": "find bravo", "k": 3, "conversation_id": conversation_id},
        headers=_auth(user_id),
    )

    assert response.status_code == 200
    # No rewrite step ran -> null, and the model was never asked to rewrite.
    assert response.json()["rewritten_question"] is None
    assert stub.rewrite_calls == []


async def test_rewrite_runs_with_history_and_drives_retrieval(env: _Env) -> None:
    stub = _RewriteThenAnswerGenerator(rewritten="find bravo")
    app.dependency_overrides[get_generation_provider] = lambda: stub
    user_id = await _seed_user_chunks(env, ["bravo banana"])
    created = await env.client.post(CONV, json={}, headers=_auth(user_id))
    conversation_id = created.json()["id"]

    # Turn 1 populates history (empty history -> no rewrite here).
    await env.client.post(
        QUERY,
        json={"question": "find bravo", "k": 3, "conversation_id": conversation_id},
        headers=_auth(user_id),
    )

    # Turn 2 is a follow-up that embeds orthogonal to the corpus: it retrieves
    # nothing on its own, so a non-empty citations set proves the REWRITTEN query
    # ("find bravo") drove retrieval.
    follow_up = await env.client.post(
        QUERY,
        json={"question": "second one", "k": 3, "conversation_id": conversation_id},
        headers=_auth(user_id),
    )

    assert follow_up.status_code == 200
    body = follow_up.json()
    assert body["rewritten_question"] == "find bravo"
    assert body["citations"]  # retrieval succeeded only because of the rewrite
    assert len(stub.rewrite_calls) == 1  # rewrite fired exactly once, on turn 2

    # The ORIGINAL question is what the transcript records — not the rewrite.
    detail = await env.client.get(f"{CONV}/{conversation_id}", headers=_auth(user_id))
    messages = detail.json()["messages"]
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "second one"


async def test_rewrite_failure_degrades_to_original_and_still_answers(
    env: _Env,
) -> None:
    app.dependency_overrides[get_generation_provider] = lambda: _RewriteFailsGenerator()
    user_id = await _seed_user_chunks(env, ["bravo banana"])
    created = await env.client.post(CONV, json={}, headers=_auth(user_id))
    conversation_id = created.json()["id"]

    # Turn 1 populates history.
    await env.client.post(
        QUERY,
        json={"question": "find bravo", "k": 3, "conversation_id": conversation_id},
        headers=_auth(user_id),
    )

    # Turn 2: the rewrite raises, but the original question already retrieves, so
    # the request still succeeds and answers.
    follow_up = await env.client.post(
        QUERY,
        json={"question": "find bravo", "k": 3, "conversation_id": conversation_id},
        headers=_auth(user_id),
    )

    assert follow_up.status_code == 200
    body = follow_up.json()
    assert body["answer"] == "ANSWER"  # rewrite failure did not fail the request
    assert body["citations"]  # retrieval used the original question
    # The step ran (history was non-empty), so rewritten_question is non-null even
    # though the rewrite degraded to the original.
    assert body["rewritten_question"] == "find bravo"


async def test_rewritten_question_null_without_conversation(env: _Env) -> None:
    user_id = await _seed_user_chunks(env, ["bravo banana"])

    response = await env.client.post(
        QUERY, json={"question": "find bravo", "k": 3}, headers=_auth(user_id)
    )

    assert response.status_code == 200
    assert response.json()["rewritten_question"] is None
