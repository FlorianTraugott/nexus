"""Web-search providers: turn a query into structured WebSearchFindings.

Callers (the web-search agent) depend only on the SearchProvider protocol, so
the concrete backend is config-swappable. The default is the offline no-op
NullSearchProvider — live web search is a billable external call, so the Tavily
backend is explicit opt-in and only built when an API key is present.
"""

from functools import lru_cache
from typing import Any, Protocol

import httpx
from tavily import AsyncTavilyClient
from tavily.errors import (
    BadRequestError,
    ForbiddenError,
    InvalidAPIKeyError,
    KeylessUnsupportedEndpointError,
    MissingAPIKeyError,
    UsageLimitExceededError,
)
from tavily.errors import TimeoutError as TavilyTimeoutError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.research import WebSearchFindings, WebSearchHit

log = get_logger(__name__)

# Operational failures a live search can hit: API rejections, rate limits,
# timeouts, and transport errors. Translated to SearchProviderError so the agent
# can degrade on these alone — and NOT on programming errors (a mapping bug,
# attribute typo), which must keep propagating instead of hiding as a warning.
# Tavily's error classes share no common base, so they are listed explicitly.
_PROVIDER_ERRORS: tuple[type[Exception], ...] = (
    BadRequestError,
    ForbiddenError,
    InvalidAPIKeyError,
    KeylessUnsupportedEndpointError,
    MissingAPIKeyError,
    UsageLimitExceededError,  # also covers its subclass TavilyKeylessLimitError
    TavilyTimeoutError,
    httpx.HTTPError,
)


class SearchProviderError(Exception):
    """A live search provider failed at call time (network/API/rate-limit).

    Narrow on purpose: only expected operational failures are wrapped in this,
    so callers degrade on it without swallowing genuine bugs.
    """


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
    it never raises at construction). Expected operational failures are wrapped
    in SearchProviderError so the agent can degrade; the agent — not this layer —
    decides pipeline policy. Response mapping runs outside that translation, so a
    bug there surfaces as itself rather than masquerading as a provider outage.
    """

    def __init__(self, api_key: str) -> None:
        self._client = AsyncTavilyClient(api_key=api_key)

    async def search(self, query: str, *, max_results: int) -> WebSearchFindings:
        try:
            response = await self._client.search(query, max_results=max_results)
        except _PROVIDER_ERRORS as exc:
            raise SearchProviderError(str(exc)) from exc
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
