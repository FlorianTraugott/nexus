"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.api.v1 import auth, documents
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import configure_middleware
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log = get_logger(__name__)
    log.info("startup", environment=get_settings().ENVIRONMENT)
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
    app.include_router(documents.router, prefix="/api/v1")
    configure_middleware(app)
    return app


app = create_app()
