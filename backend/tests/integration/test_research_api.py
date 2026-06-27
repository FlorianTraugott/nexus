"""Tests for the research endpoint (full pipeline over HTTP), kept offline.

Reuses the query endpoint's harness: in-memory SQLite, an ephemeral Chroma
store, and provider factories overridden with offline fakes. The generator is a
ScriptedGenerator that returns the right canned JSON per stage, so a real run
flows web → kb → summarise → report with no network.
"""

import json
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
from tests.fakes import FakeSearchProvider, ephemeral_store

from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import DocumentSourceType, User
from app.db.repositories import document as document_repo
from app.db.session import get_db
from app.main import app
from app.services.embeddings import get_embedding_provider
from app.services.generation import get_generation_provider
from app.services.search import SearchProviderError, get_search_provider
from app.services.vector_store import VectorStore, get_vector_store

RESEARCH = "/api/v1/research"

_VECTORS = {
    "bravo banana": [0.0, 1.0, 0.0],
    "looking for bravo": [0.0, 1.0, 0.0],
}

_SUMMARY_JSON = json.dumps({"key_points": ["kp"], "abstract": "An abstract."})
_REPORT_JSON = json.dumps(
    {
        "title": "Report Title",
        "sections": [{"heading": "Intro", "body": "Body text."}],
        "markdown": "# Report Title\n\n## Intro\n\nBody text.",
    }
)


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


class BoomEmbedder:
    """Embedder that fails the KB step, to exercise the pipeline-error path."""

    @property
    def dimension(self) -> int:
        return 3

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedder down")

    async def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("embedder down")


class ScriptedGenerator:
    """Returns the right canned JSON per stage, branching on the system prompt."""

    def __init__(self, *, summary: str = _SUMMARY_JSON, report: str = _REPORT_JSON):
        self.summary = summary
        self.report = report
        self.calls: list[tuple[str, str]] = []

    async def generate(
        self, system: str, prompt: str, *, json_mode: bool = False
    ) -> str:
        self.calls.append((system, prompt))
        if "summariser" in system:
            return self.summary
        if "report writer" in system:
            return self.report
        raise AssertionError("unexpected system prompt")


@dataclass
class _Env:
    client: AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    store: VectorStore
    embedder: MappingEmbedder | BoomEmbedder
    generator: ScriptedGenerator
    search: FakeSearchProvider


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

    environment = _Env(
        client=None,  # type: ignore[arg-type]
        session_factory=session_factory,
        store=ephemeral_store(),
        embedder=MappingEmbedder(),
        generator=ScriptedGenerator(),
        search=FakeSearchProvider(),
    )

    # Read from the env so a test can swap a provider before posting.
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: environment.store
    app.dependency_overrides[get_embedding_provider] = lambda: environment.embedder
    app.dependency_overrides[get_generation_provider] = lambda: environment.generator
    app.dependency_overrides[get_search_provider] = lambda: environment.search

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        environment.client = client
        yield environment

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

        vectors = await MappingEmbedder().embed_texts(contents)
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


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


async def test_research_runs_full_pipeline_to_done(env: _Env) -> None:
    user_id = await _seed_user_chunks(env, ["bravo banana"])

    response = await env.client.post(
        RESEARCH, json={"topic": "looking for bravo"}, headers=_auth(user_id)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "done"
    assert body["error"] is None
    assert body["warnings"] == []
    assert body["report"]["title"] == "Report Title"
    assert body["summary"]["abstract"] == "An abstract."
    assert body["web"]["hits"]  # supporting evidence surfaced
    assert body["kb"]["findings"]
    assert "user_id" not in body  # never leaked


async def test_research_requires_authentication(env: _Env) -> None:
    response = await env.client.post(RESEARCH, json={"topic": "looking for bravo"})
    assert response.status_code in (401, 403)


async def test_research_is_scoped_to_token_user(env: _Env) -> None:
    mine = await _seed_user_chunks(env, ["bravo banana"])
    other = await _seed_user_chunks(env, ["bravo banana"])

    response = await env.client.post(
        # A payload-supplied id must be ignored; scoping comes from the token.
        RESEARCH,
        json={"topic": "looking for bravo", "user_id": str(other)},
        headers=_auth(mine),
    )

    assert response.status_code == 200
    body = response.json()
    finding_docs = {f["document_id"] for f in body["kb"]["findings"]}
    # Only the token user's single document is retrievable.
    assert len(finding_docs) == 1


async def test_research_rejects_k_above_max(env: _Env) -> None:
    user_id = await _seed_user_chunks(env, ["bravo banana"])

    response = await env.client.post(
        RESEARCH,
        json={"topic": "looking for bravo", "k": 9999},
        headers=_auth(user_id),
    )

    assert response.status_code == 422


async def test_research_pipeline_failure_is_200_with_error(env: _Env) -> None:
    user_id = await _seed_user_chunks(env, ["bravo banana"])
    env.embedder = BoomEmbedder()  # KB step fails

    response = await env.client.post(
        RESEARCH, json={"topic": "looking for bravo"}, headers=_auth(user_id)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["report"] is None
    assert body["summary"] is None
    assert body["stage"] == "kb_query"  # halted at the failing stage
    assert "embedder down" in body["error"]
    assert body["web"]["hits"]  # web ran before the failure


async def test_research_web_degraded_still_completes(env: _Env) -> None:
    user_id = await _seed_user_chunks(env, ["bravo banana"])
    env.search = FakeSearchProvider(error=SearchProviderError("down"))

    response = await env.client.post(
        RESEARCH, json={"topic": "looking for bravo"}, headers=_auth(user_id)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "done"
    assert body["error"] is None
    assert body["report"] is not None
    assert body["web"]["hits"] == []
    assert body["warnings"] == ["web search unavailable"]
