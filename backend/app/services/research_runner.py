"""Background research runner: run the pipeline for one persisted task.

Mirrors ingest_document/run_ingestion: the thin entrypoint owns its own session
(a background task cannot use request-scoped Depends), and the job function takes
an injected session + optional providers so tests drive the real logic offline.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import run_research
from app.core.logging import get_logger
from app.db.repositories import research as research_repo
from app.db.session import AsyncSessionLocal
from app.schemas.research import ResearchResponse, ResearchState
from app.services.embeddings import EmbeddingProvider
from app.services.generation import GenerationProvider
from app.services.search import SearchProvider
from app.services.vector_store import VectorStore

log = get_logger(__name__)


async def run_research_task(task_id: uuid.UUID) -> None:
    """Entry point for the background task; owns its own session."""
    async with AsyncSessionLocal() as session:
        await run_research_job(session, task_id)


async def run_research_job(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    search: SearchProvider | None = None,
    embedder: EmbeddingProvider | None = None,
    store: VectorStore | None = None,
    generator: GenerationProvider | None = None,
) -> None:
    task = await research_repo.get_task(session, task_id)
    if task is None:
        return

    # Commit RUNNING before the long pipeline so pollers observe it and a crash
    # leaves a visible RUNNING task rather than one stuck at PENDING.
    await research_repo.set_task_running(session, task)
    await session.commit()

    try:
        state = ResearchState(topic=task.topic, user_id=task.user_id, k=task.k)
        # No providers passed -> run_research lazy-resolves the configured ones.
        state = await run_research(
            state,
            session,
            search=search,
            embedder=embedder,
            store=store,
            generator=generator,
        )
        # A recorded pipeline failure (state.error set) is a COMPLETED task with
        # the error carried inside result — run_research never raises, so reaching
        # here always means the run finished, successfully or not.
        result = ResearchResponse(
            topic=state.topic,
            stage=state.stage,
            web=state.web,
            kb=state.kb,
            summary=state.summary,
            report=state.report,
            warnings=state.warnings,
            error=state.error,
        )
        await research_repo.set_task_completed(
            session, task, result.model_dump(mode="json")
        )
        await session.commit()
    except Exception as exc:
        # Infrastructure failure (DB, serialisation) — NOT a pipeline error, which
        # run_research swallows into state.error. Don't leave the task stuck in
        # RUNNING: roll back the failed unit and mark FAILED in a fresh transaction.
        log.error(
            "research_task_failed", task_id=str(task_id), error=str(exc), exc_info=True
        )
        await session.rollback()
        task = await research_repo.get_task(session, task_id)
        if task is not None:
            await research_repo.set_task_failed(
                session, task, f"{type(exc).__name__}: {exc}"
            )
            await session.commit()
