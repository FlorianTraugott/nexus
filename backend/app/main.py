"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.api.v1 import auth, conversations, documents, query, research, vision
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import configure_middleware
from app.core.startup import (
    check_vector_store_consistency,
    require_openai_key,
    sweep_stranded_research_tasks,
)
from app.db.session import AsyncSessionLocal, engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log = get_logger(__name__)
    settings = get_settings()
    log.info("startup", environment=settings.ENVIRONMENT)

    # FATAL-before-best-effort: the key check (no DB) and the consistency check
    # abort startup if they raise; the sweep is best-effort so its failure is
    # caught and logged. The startup session closes before `yield`, so nothing
    # here can hand a poisoned session to a request handler.
    require_openai_key(settings)
    async with AsyncSessionLocal() as session:
        await check_vector_store_consistency(session)
        try:
            await sweep_stranded_research_tasks(session)
        except Exception:
            await session.rollback()
            log.error("stranded_research_task_sweep_failed", exc_info=True)

    yield
    await engine.dispose()
    log.info("shutdown")


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="Nexus AI",
        version="0.1.0",
        description="Multimodal AI research assistant.",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(conversations.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(query.router, prefix="/api/v1")
    app.include_router(research.router, prefix="/api/v1")
    app.include_router(vision.router, prefix="/api/v1")
    configure_middleware(app)
    return app


app = create_app()
