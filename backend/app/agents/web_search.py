"""Web-search agent: the first pipeline stage.

Runs the injected SearchProvider over the topic and records the findings on the
state, then advances to the KB-query stage. The provider is passed in (never
resolved here) so tests drive the agent with a fake — no key, no network.

Web search is best-effort: a provider failure degrades to empty findings plus a
warning so the run continues, since the knowledge base can still answer. Only
failures that make the whole run meaningless belong in state.error.
"""

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.research import ResearchStage, ResearchState, WebSearchFindings
from app.services.search import SearchProvider

log = get_logger(__name__)


async def run_web_search(
    state: ResearchState, provider: SearchProvider
) -> ResearchState:
    """Populate state.web from the provider and advance to the KB-query stage."""
    max_results = get_settings().SEARCH_MAX_RESULTS
    try:
        state.web = await provider.search(state.topic, max_results=max_results)
    except Exception as exc:
        # Network / 5xx / rate-limit / malformed response: degrade, don't abort.
        log.warning("web_search_failed", topic=state.topic, error=str(exc))
        state.warnings.append("web search unavailable")
        state.web = WebSearchFindings(query=state.topic, hits=[])

    state.stage = ResearchStage.KB_QUERY
    return state
