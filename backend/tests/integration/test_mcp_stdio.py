"""Live MCP stdio round-trip: a real client spawns the server and calls a tool.

This is the end-to-end check the offline unit tests can't give: it launches
`python -m app.mcp.server` as a subprocess and talks to it with the mcp client
over stdio, proving the registered tools are discoverable and callable by a real
client. It stays offline — SEARCH_PROVIDER defaults to "null", so web_search
returns empty findings with no network. kb_search's full path (Postgres + a
seeded user + embeddings) is a documented manual check, not exercised here.
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

_BACKEND = Path(__file__).resolve().parents[2]


def _server_params() -> StdioServerParameters:
    # The spawned server instantiates Settings at import, so it needs the
    # no-default fields in its environment. The stdio client forwards only a
    # minimal whitelist (PATH/HOME/...), so we inject them explicitly here
    # rather than relying on .env; cwd=backend still lets it find .env for the
    # rest. These mirror tests/conftest.py and keep the run fully offline.
    env = {
        **get_default_environment(),
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "POSTGRES_USER": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_DB": "test",
        "POSTGRES_HOST": "localhost",
        "JWT_SECRET_KEY": "test-secret-key-not-for-production",
    }
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp.server"],
        cwd=str(_BACKEND),
        env=env,
    )


async def test_stdio_round_trip_lists_and_calls_tools() -> None:
    # asyncio.timeout guards against a hung subprocess (e.g. a server that fails
    # to start); the round-trip itself is fast.
    async with (
        stdio_client(_server_params()) as (read, write),
        ClientSession(read, write) as session,
        asyncio.timeout(30),
    ):
        await session.initialize()

        listed = await session.list_tools()
        tools = {tool.name: tool for tool in listed.tools}
        # Both tools are discoverable by a real client over the wire.
        assert {"web_search", "kb_search"} <= set(tools)
        # Pydantic return types survive as output schemas across the wire.
        assert tools["web_search"].outputSchema is not None
        assert tools["kb_search"].outputSchema is not None
        assert tools["kb_search"].inputSchema["required"] == ["query"]

        # A real call_tool round-trip: the offline NullSearchProvider returns
        # empty findings, proving the full client->server->tool path is wired
        # without any network.
        result = await session.call_tool("web_search", {"query": "anything"})
        assert not result.isError
        assert result.structuredContent == {"query": "anything", "hits": []}
