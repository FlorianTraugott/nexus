"""Web-search providers: turn a query into structured WebSearchFindings.

Callers (the web-search agent) depend only on the SearchProvider protocol, so
the concrete backend is config-swappable. The default is the offline no-op
NullSearchProvider — live web search is a billable external call, so the Tavily
backend is explicit opt-in and only built when an API key is present.
"""

from functools import lru_cache
from typing import Any, Protocol

from tavily import AsyncTavilyClient

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.research import WebSearchFindings, WebSearchHit

log = get_logger(__name__)


class SearchProvider(Protocol):
    """Runs a web search and returns structured findings."""

    async def search(self, query: str, *, max_results: int) -> WebSearchFindings:
        """Return findings for the query; hits may be empty."""
        ...


class NullSearchProvider:
    """No-op provider: always returns empty findings, never makes a call.

    The safe default and the fallback when Tavily is selected without a key, so
    a normal run stays green offline with web search simply contributing nothing.
    """

    async def search(self, query: str, *, max_results: int) -> WebSearchFindings:
        return WebSearchFindings(query=query, hits=[])


class TavilySearchProvider:
    """Live web search backed by Tavily's native async client.

    Assumes a valid key (the factory only builds this when one is configured, so
    it never raises at construction). Call-time errors are the caller's to
    handle: search() lets them propagate so the agent can degrade and record a
    warning rather than this layer deciding pipeline policy.
    """

    def __init__(self, api_key: str) -> None:
        self._client = AsyncTavilyClient(api_key=api_key)

    async def search(self, query: str, *, max_results: int) -> WebSearchFindings:
        response = await self._client.search(query, max_results=max_results)
        hits = [self._to_hit(item) for item in response.get("results", [])]
        return WebSearchFindings(query=query, hits=hits)

    @staticmethod
    def _to_hit(item: dict[str, Any]) -> WebSearchHit:
        # Tavily's "content" is the result snippet; "score" may be absent.
        return WebSearchHit(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("content", ""),
            score=item.get("score"),
        )


@lru_cache
def get_search_provider() -> SearchProvider:
    """Build the configured provider once and reuse it across requests."""
    settings = get_settings()
    if settings.SEARCH_PROVIDER == "null":
        return NullSearchProvider()
    if settings.SEARCH_PROVIDER == "tavily":
        if not settings.TAVILY_API_KEY:
            # Expected config, not an error: degrade to the no-op so the app runs.
            log.warning("search_provider_no_key", provider="tavily")
            return NullSearchProvider()
        return TavilySearchProvider(api_key=settings.TAVILY_API_KEY)
    raise ValueError(f"Unknown search provider: {settings.SEARCH_PROVIDER!r}")
