"""Tests for the research orchestrator: stage sequencing and halt-on-failure.

Offline: deterministic embedder, in-memory Chroma, a fake search provider, and a
scripted generator, so the full pipeline runs with no network or real provider.
"""

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes import FakeSearchProvider, ephemeral_store

from app.agents import orchestrator
from app.agents.orchestrator import run_research
from app.db.models import DocumentChunk, DocumentSourceType, User
from app.db.repositories import document as document_repo
from app.schemas.research import ResearchStage, ResearchState
from app.services.search import SearchProviderError
from app.services.vector_store import VectorStore

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

    async def generate(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        if "summariser" in system:
            return self.summary
        if "report writer" in system:
            return self.report
        raise AssertionError("unexpected system prompt")


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


async def _state(session: AsyncSession) -> ResearchState:
    user_id = await _make_user(session)
    return ResearchState(topic="looking for bravo", user_id=user_id)


def _exploding_factory(name: str):
    def factory():
        raise AssertionError(f"{name} should not be constructed")

    return factory


async def test_full_success_runs_all_stages_to_done(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Prove injected fakes are used: make every factory explode if called.
    for name in (
        "get_search_provider",
        "get_embedding_provider",
        "get_vector_store",
        "get_generation_provider",
    ):
        monkeypatch.setattr(orchestrator, name, _exploding_factory(name))

    embedder, store = MappingEmbedder(), ephemeral_store()
    state = await _state(db_session)
    await _seed(db_session, store, embedder, state.user_id, ["bravo banana"])
    generator = ScriptedGenerator()

    result = await run_research(
        state,
        db_session,
        search=FakeSearchProvider(),
        embedder=embedder,
        store=store,
        generator=generator,
    )

    assert result.web is not None and result.web.hits
    assert result.kb is not None and result.kb.findings
    assert result.summary is not None and result.summary.abstract == "An abstract."
    assert result.report is not None and result.report.title == "Report Title"
    assert result.stage is ResearchStage.DONE
    assert result.error is None
    assert result.warnings == []


async def test_kb_failure_halts_and_records_error(db_session: AsyncSession) -> None:
    state = await _state(db_session)
    generator = ScriptedGenerator()

    result = await run_research(
        state,
        db_session,
        search=FakeSearchProvider(),
        embedder=BoomEmbedder(),
        store=ephemeral_store(),
        generator=generator,
    )

    assert result.web is not None  # web ran before the failure
    assert result.kb is None
    assert result.summary is None and result.report is None
    assert result.stage is ResearchStage.KB_QUERY  # left at the failing stage
    assert "embedder down" in (result.error or "")
    assert generator.calls == []  # summarise/report never ran


async def test_summarise_failure_halts_and_records_error(
    db_session: AsyncSession,
) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    state = await _state(db_session)
    await _seed(db_session, store, embedder, state.user_id, ["bravo banana"])
    generator = ScriptedGenerator(summary="not valid json")

    result = await run_research(
        state,
        db_session,
        search=FakeSearchProvider(),
        embedder=embedder,
        store=store,
        generator=generator,
    )

    assert result.kb is not None  # kb succeeded
    assert result.summary is None
    assert result.report is None
    assert result.stage is ResearchStage.SUMMARISE
    assert "MalformedSummaryError" in (result.error or "")


async def test_web_degraded_does_not_halt(db_session: AsyncSession) -> None:
    embedder, store = MappingEmbedder(), ephemeral_store()
    state = await _state(db_session)
    await _seed(db_session, store, embedder, state.user_id, ["bravo banana"])

    result = await run_research(
        state,
        db_session,
        search=FakeSearchProvider(error=SearchProviderError("down")),
        embedder=embedder,
        store=store,
        generator=ScriptedGenerator(),
    )

    # Web degraded to empty + a warning, but the run still completed.
    assert result.web is not None and result.web.hits == []
    assert result.warnings == ["web search unavailable"]
    assert result.stage is ResearchStage.DONE
    assert result.error is None
    assert result.report is not None
