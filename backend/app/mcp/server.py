"""MCP server: expose Nexus tools over the Model Context Protocol.

Wraps the existing service layer so any MCP client (e.g. Claude) calls the same
search/retrieval the HTTP API uses — no parallel logic. Each tool is a thin
decorated wrapper that resolves providers via the existing factories and
delegates to a pure inner function taking them injected, so the logic stays
offline-testable without an MCP client. Runs over stdio (the local deployment).
"""

from mcp.server.fastmcp import FastMCP

from app.core.config import get_settings
from app.schemas.research import WebSearchFindings
from app.services.search import SearchProvider, get_search_provider

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


def main() -> None:
    """Run the MCP server over stdio (FastMCP's default transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
