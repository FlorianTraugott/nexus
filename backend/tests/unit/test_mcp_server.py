"""Tests for the MCP server's web_search tool, kept offline.

The inner function is driven with the FakeSearchProvider (canned hits); the
registered tool is exercised through FastMCP's own call path with the default
NullSearchProvider (empty findings). Wiring is proven in-process — no MCP client,
no network.
"""

from tests.fakes import FakeSearchProvider

from app.core.config import get_settings
from app.mcp.server import _run_web_search, mcp
from app.schemas.research import WebSearchFindings, WebSearchHit


async def test_inner_uses_injected_provider_and_default_max_results() -> None:
    hits = [WebSearchHit(title="T", url="https://e.com", snippet="s", score=0.5)]
    provider = FakeSearchProvider(hits=hits)

    findings = await _run_web_search("topic", provider=provider)

    assert isinstance(findings, WebSearchFindings)
    assert findings.query == "topic"
    assert [h.title for h in findings.hits] == ["T"]
    # Defaulted max_results comes from settings, not a hardcoded literal.
    assert provider.calls == [("topic", get_settings().SEARCH_MAX_RESULTS)]


async def test_inner_respects_max_results_override() -> None:
    provider = FakeSearchProvider()

    await _run_web_search("topic", 3, provider=provider)

    assert provider.calls == [("topic", 3)]


async def test_tool_registered_with_input_and_output_schemas() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert "web_search" in tools
    tool = tools["web_search"]
    assert "query" in tool.inputSchema["properties"]
    assert tool.inputSchema["required"] == ["query"]
    assert tool.outputSchema is not None


async def test_tool_call_offline_returns_empty_findings() -> None:
    # SEARCH_PROVIDER defaults to "null", so a real call_tool round-trip returns
    # empty findings with no network — proving the full registered path is wired.
    result = await mcp.call_tool("web_search", {"query": "anything"})

    # call_tool returns (content, structured_content); assert the structured half.
    assert result[1] == {"query": "anything", "hits": []}


async def test_kb_search_tool_registered_with_input_and_output_schemas() -> None:
    # Registration is offline (introspection only); the call path needs a DB and
    # is exercised in tests/integration/test_mcp_kb_search.py.
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert "kb_search" in tools
    tool = tools["kb_search"]
    assert "query" in tool.inputSchema["properties"]
    assert tool.inputSchema["required"] == ["query"]
    assert tool.outputSchema is not None
