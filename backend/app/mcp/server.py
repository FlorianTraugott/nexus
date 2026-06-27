"""MCP server: expose Nexus tools over the Model Context Protocol.

Wraps the existing service layer so any MCP client (e.g. Claude) calls the same
search/retrieval the HTTP API uses — no parallel logic. Each tool is a thin
decorated wrapper that resolves providers via the existing factories and
delegates to a pure inner function taking them injected, so the logic stays
offline-testable without an MCP client. Runs over stdio (the local deployment).
"""

import os
import uuid

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.repositories.user import get_user_by_id
from app.db.session import AsyncSessionLocal
from app.schemas.research import KBFindings, WebSearchFindings
from app.services.embeddings import EmbeddingProvider
from app.services.retrieval import retrieve, to_finding
from app.services.search import SearchProvider, get_search_provider
from app.services.vector_store import VectorStore

mcp = FastMCP(
    "nexus",
    instructions="Search and retrieval tools over a Nexus document corpus.",
)


async def _run_web_search(
    query: str,
    max_results: int | None = None,
    *,
    provider: SearchProvider | None = None,
) -> WebSearchFindings:
    """Search the web for the query; provider is injectable so tests stay offline."""
    # Lazy resolution mirrors retrieve()/run_research(): use what's injected, else
    # the configured provider (the offline NullSearchProvider by default).
    provider = provider or get_search_provider()
    n = max_results if max_results is not None else get_settings().SEARCH_MAX_RESULTS
    return await provider.search(query, max_results=n)


@mcp.tool(
    name="web_search",
    description="Search the web for a query and return structured findings.",
)
async def web_search(query: str, max_results: int | None = None) -> WebSearchFindings:
    """MCP tool wrapper: resolve the provider via config, then run the search."""
    return await _run_web_search(query, max_results)


_USER_ID_ENV = "NEXUS_MCP_USER_ID"


class MCPIdentityError(Exception):
    """The configured MCP user is unset, malformed, or not an active user.

    A stdio MCP client carries no token, so NEXUS_MCP_USER_ID is the only
    identity. A bad value must fail loudly here rather than ever fall back to
    unscoped or cross-user retrieval.
    """


async def _resolve_user_id(session: AsyncSession) -> uuid.UUID:
    """Resolve NEXUS_MCP_USER_ID to a validated user id, or raise.

    The same check the HTTP layer's get_current_user runs: parse the id, look the
    user up, require is_active. There is deliberately no unscoped fallback.
    """
    raw = os.environ.get(_USER_ID_ENV)
    if not raw:
        raise MCPIdentityError(f"{_USER_ID_ENV} is not set")
    try:
        user_id = uuid.UUID(raw)
    except ValueError:
        raise MCPIdentityError(f"{_USER_ID_ENV} is not a valid UUID: {raw!r}") from None
    user = await get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise MCPIdentityError(f"{_USER_ID_ENV} is not an active user: {user_id}")
    return user_id


async def _run_kb_search(
    session: AsyncSession,
    query: str,
    k: int | None = None,
    *,
    embedder: EmbeddingProvider | None = None,
    store: VectorStore | None = None,
) -> KBFindings:
    """Resolve the configured user, run owner-scoped retrieval, map to findings.

    Identity is validated before any retrieval; providers are injectable so tests
    stay offline. Mirrors _run_web_search and reuses the exact retrieve() path.
    """
    user_id = await _resolve_user_id(session)
    results = await retrieve(
        session, query, user_id, k=k, embedder=embedder, store=store
    )
    return KBFindings(query=query, findings=[to_finding(result) for result in results])


@mcp.tool(
    name="kb_search",
    description="Search the configured user's Nexus document corpus and return "
    "structured findings.",
)
async def kb_search(query: str, k: int | None = None) -> KBFindings:
    """MCP tool wrapper: open a session, then run owner-scoped KB retrieval."""
    async with AsyncSessionLocal() as session:
        return await _run_kb_search(session, query, k)


def main() -> None:
    """Run the MCP server over stdio (FastMCP's default transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
