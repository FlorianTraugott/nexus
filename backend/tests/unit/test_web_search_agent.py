"""Tests for the web-search agent: state population and graceful degradation.

Offline only — the agent is driven with a FakeSearchProvider / NullSearchProvider,
so no key and no network are involved.
"""

import uuid
from types import SimpleNamespace

from tests.fakes import FakeSearchProvider

from app.agents import web_search
from app.agents.web_search import run_web_search
from app.schemas.research import ResearchStage, ResearchState
from app.services.search import NullSearchProvider


def _state() -> ResearchState:
    return ResearchState(topic="quantum error correction", user_id=uuid.uuid4())


def _fixed_max_results(monkeypatch, n: int) -> None:
    monkeypatch.setattr(
        web_search, "get_settings", lambda: SimpleNamespace(SEARCH_MAX_RESULTS=n)
    )


async def test_normal_path_populates_web_and_advances_stage(monkeypatch) -> None:
    _fixed_max_results(monkeypatch, 4)
    provider = FakeSearchProvider()

    result = await run_web_search(_state(), provider)

    assert provider.calls == [("quantum error correction", 4)]
    assert result.web is not None
    assert [h.title for h in result.web.hits] == ["Example"]
    assert result.stage is ResearchStage.KB_QUERY
    assert result.warnings == []
    assert result.error is None


async def test_missing_key_path_yields_empty_findings_without_error(
    monkeypatch,
) -> None:
    _fixed_max_results(monkeypatch, 5)
    # With no key the factory hands the agent the no-op provider; the run still
    # completes with empty findings and is not marked failed.
    result = await run_web_search(_state(), NullSearchProvider())

    assert result.web is not None
    assert result.web.hits == []
    assert result.stage is ResearchStage.KB_QUERY
    assert result.warnings == []
    assert result.error is None


async def test_provider_failure_degrades_to_warning(monkeypatch) -> None:
    _fixed_max_results(monkeypatch, 5)
    provider = FakeSearchProvider(fail=True)

    result = await run_web_search(_state(), provider)

    assert result.web is not None
    assert result.web.hits == []
    assert result.warnings == ["web search unavailable"]
    assert result.error is None  # a failed web search does not fail the run
    assert result.stage is ResearchStage.KB_QUERY
