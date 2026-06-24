"""Tests for the search provider abstraction and the provider factory.

All offline: the Tavily client's network call is monkeypatched, and no test
needs a real key.
"""

from types import SimpleNamespace

import pytest
from tests.fakes import FakeSearchProvider

from app.services import search as search_module
from app.services.search import (
    NullSearchProvider,
    TavilySearchProvider,
    get_search_provider,
)


async def test_null_provider_returns_empty_findings() -> None:
    findings = await NullSearchProvider().search("anything", max_results=5)

    assert findings.query == "anything"
    assert findings.hits == []


async def test_fake_provider_is_deterministic_and_records_calls() -> None:
    provider = FakeSearchProvider()

    findings = await provider.search("topic", max_results=3)

    assert provider.calls == [("topic", 3)]
    assert [h.title for h in findings.hits] == ["Example"]


async def test_fake_provider_failure_mode_raises() -> None:
    with pytest.raises(RuntimeError, match="simulated provider failure"):
        await FakeSearchProvider(fail=True).search("topic", max_results=3)


async def test_tavily_provider_maps_response_to_findings(monkeypatch) -> None:
    captured: dict = {}

    async def fake_search(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return {
            "results": [
                {
                    "title": "A",
                    "url": "https://a.com",
                    "content": "snippet a",
                    "score": 0.42,
                },
                # No score key: must map to None, not crash.
                {"title": "B", "url": "https://b.com", "content": "snippet b"},
            ]
        }

    provider = TavilySearchProvider(api_key="x")
    monkeypatch.setattr(provider._client, "search", fake_search)

    findings = await provider.search("my query", max_results=2)

    assert captured["query"] == "my query"
    assert captured["max_results"] == 2
    assert [(h.title, h.snippet, h.score) for h in findings.hits] == [
        ("A", "snippet a", 0.42),
        ("B", "snippet b", None),
    ]


async def test_tavily_provider_propagates_call_time_errors(monkeypatch) -> None:
    async def boom(query, **kwargs):
        raise RuntimeError("network down")

    provider = TavilySearchProvider(api_key="x")
    monkeypatch.setattr(provider._client, "search", boom)

    # The provider does not swallow; the agent owns the degrade policy.
    with pytest.raises(RuntimeError, match="network down"):
        await provider.search("q", max_results=1)


def _settings(**overrides):
    base = {"SEARCH_PROVIDER": "null", "TAVILY_API_KEY": "", "SEARCH_MAX_RESULTS": 5}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_factory_builds_null_provider_by_default(monkeypatch) -> None:
    get_search_provider.cache_clear()
    monkeypatch.setattr(search_module, "get_settings", lambda: _settings())

    assert isinstance(get_search_provider(), NullSearchProvider)
    get_search_provider.cache_clear()


def test_factory_builds_tavily_when_selected_with_key(monkeypatch) -> None:
    get_search_provider.cache_clear()
    monkeypatch.setattr(
        search_module,
        "get_settings",
        lambda: _settings(SEARCH_PROVIDER="tavily", TAVILY_API_KEY="real-key"),
    )

    assert isinstance(get_search_provider(), TavilySearchProvider)
    get_search_provider.cache_clear()


def test_factory_falls_back_to_null_when_tavily_has_no_key(monkeypatch) -> None:
    get_search_provider.cache_clear()
    monkeypatch.setattr(
        search_module,
        "get_settings",
        lambda: _settings(SEARCH_PROVIDER="tavily", TAVILY_API_KEY=""),
    )

    # Missing key is expected config, not a crash: degrade to the no-op provider.
    assert isinstance(get_search_provider(), NullSearchProvider)
    get_search_provider.cache_clear()


def test_factory_rejects_unknown_provider(monkeypatch) -> None:
    get_search_provider.cache_clear()
    monkeypatch.setattr(
        search_module, "get_settings", lambda: _settings(SEARCH_PROVIDER="bogus")
    )

    with pytest.raises(ValueError, match="Unknown search provider"):
        get_search_provider()
    get_search_provider.cache_clear()
