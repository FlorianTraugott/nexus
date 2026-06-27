"""KB-query agent: the knowledge-base stage of the research pipeline.

Runs owner-scoped retrieval over the topic and records the matching chunks on
the state, then advances to the summarise stage.

Unlike the web-search agent this stage is critical, not best-effort: the
knowledge base is the user's own corpus, so a retrieval failure is NOT degraded
here — it propagates so the orchestration layer can mark the run failed. An
empty result is a normal outcome (the corpus simply had no match), recorded as
empty findings, never a warning or error.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.research import KBFindings, ResearchStage, ResearchState
from app.services.embeddings import EmbeddingProvider
from app.services.retrieval import retrieve, to_finding
from app.services.vector_store import VectorStore


async def run_kb_query(
    state: ResearchState,
    session: AsyncSession,
    *,
    embedder: EmbeddingProvider | None = None,
    store: VectorStore | None = None,
) -> ResearchState:
    """Populate state.kb from owner-scoped retrieval; advance to summarise."""
    # state.k is None or > 0 (schema-validated); retrieve() defaults/validates it.
    results = await retrieve(
        session,
        state.topic,
        state.user_id,
        k=state.k,
        embedder=embedder,
        store=store,
    )
    state.kb = KBFindings(
        query=state.topic,
        findings=[to_finding(result) for result in results],
    )
    state.stage = ResearchStage.SUMMARISE
    return state
