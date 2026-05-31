"""Async database engine and session management.

This sets up the connection to PostgreSQL using SQLAlchemy's async engine
(driven by asyncpg) and exposes `get_db`, the FastAPI dependency that hands a
fresh session to each request and cleans it up afterwards.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

# The engine manages a pool of connections to the database. It is created once
# for the whole application. Creating it does NOT open a connection yet — that
# happens lazily on first use.
engine = create_async_engine(
    settings.database_url,
    echo=settings.DEBUG,  # log every SQL statement in development
    pool_pre_ping=True,  # test a connection before using it (drops stale ones)
)

# A factory that produces new AsyncSession objects bound to the engine.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep objects usable after commit()
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield a database session for the request.

    Usage in an endpoint:
        async def handler(db: AsyncSession = Depends(get_db)):
            ...

    The session is opened per request and closed automatically when the request
    finishes. On any exception, the transaction is rolled back so a failed
    request never leaves partial data committed.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
