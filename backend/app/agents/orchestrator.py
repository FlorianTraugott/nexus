"""Research orchestrator: run the four agents in order over one ResearchState.

Stages run web search → KB query → summarise → report. Each agent mutates the
state and, on success, advances the stage to the next step, so a halted run
leaves `stage` exactly at the step that failed.

Failure policy: web search degrades internally (it never raises here), while
kb/summarise/report propagate. The first stage that raises aborts the rest —
caught at this boundary, recorded in `state.error`, and logged with a full
traceback so genuine bugs stay visible rather than silently becoming a "failed
run". Only a fully successful run reaches the DONE stage.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.kb_query import run_kb_query
from app.agents.report import run_report
from app.agents.summarise import run_summarise
from app.agents.web_search import run_web_search
from app.core.logging import get_logger
from app.schemas.research import ResearchState
from app.services.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.generation import GenerationProvider, get_generation_provider
from app.services.search import SearchProvider, get_search_provider
from app.services.vector_store import VectorStore, get_vector_store

log = get_logger(__name__)


async def run_research(
    state: ResearchState,
    session: AsyncSession,
    *,
    search: SearchProvider | None = None,
    embedder: EmbeddingProvider | None = None,
    store: VectorStore | None = None,
    generator: GenerationProvider | None = None,
) -> ResearchState:
    """Drive the pipeline to completion, or halt at the first failing stage."""
    # Lazy resolution, mirroring retrieve(): use what's injected, else the
    # configured provider. Tests inject fakes and stay offline.
    search = search or get_search_provider()
    embedder = embedder or get_embedding_provider()
    store = store or get_vector_store()
    generator = generator or get_generation_provider()

    try:
        await run_web_search(state, search)
        await run_kb_query(state, session, embedder=embedder, store=store)
        await run_summarise(state, generator)
        await run_report(state, generator)
    except Exception as exc:
        # Outermost boundary of the run: record the failure and stop. Logged
        # with the traceback so a real bug is loud, not hidden behind state.error.
        log.error(
            "research_pipeline_failed",
            stage=state.stage,
            error=str(exc),
            exc_info=True,
        )
        state.error = f"{type(exc).__name__}: {exc}"

    return state
