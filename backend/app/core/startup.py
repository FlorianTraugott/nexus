"""Fail-loud startup guards, run once from the application lifespan.

Three checks with deliberately different failure semantics (same discipline as
web-search-best-effort vs KB-critical): a missing API key and a wiped vector
store are FATAL (raise, which aborts uvicorn startup with a non-zero exit and
blocks the deploy); the stranded-task sweep is BEST-EFFORT (the lifespan logs and
continues) — a transient DB hiccup must not crash-loop the app over housekeeping.
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.repositories import document as document_repo
from app.db.repositories import research as research_repo
from app.services.vector_store import get_vector_store

log = get_logger(__name__)

_STRANDED_REASON = "interrupted by server restart"


def require_openai_key(settings: Settings) -> None:
    """FATAL: fail at startup, not at the first embed call, when the key is unset.

    Gated on ENVIRONMENT: the test suite boots with an empty key by design (fakes
    are injected). Everywhere else the app is useless without it, so refuse to
    start with a message that names the fix.
    """
    if settings.ENVIRONMENT != "test" and not settings.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is empty. Set it in .env (or the deployment "
            "environment) — embeddings and generation cannot run without it. "
            "Only ENVIRONMENT=test may start without a key (it injects fakes)."
        )


async def check_vector_store_consistency(db: AsyncSession) -> None:
    """FATAL on the wiped-volume signature: Postgres has chunks, Chroma has none.

    Asymmetric on purpose — strict equality would block boot on benign mid-ingest
    drift. Both counts are logged every boot so a PARTIAL wipe (which the binary
    check cannot see) is still discoverable. Chroma's count() is a cheap record
    count from the collection metadata, not a vector scan; offloaded to a thread to
    match how every other Chroma call is made from async code.
    """
    pg_chunks = await document_repo.count_all_chunks(db)
    chroma_chunks = await asyncio.to_thread(get_vector_store().count)
    log.info(
        "vector_store_consistency", pg_chunks=pg_chunks, chroma_chunks=chroma_chunks
    )
    if pg_chunks > 0 and chroma_chunks == 0:
        raise RuntimeError(
            f"Vector store is empty ({chroma_chunks} vectors) but Postgres has "
            f"{pg_chunks} chunks — the Chroma volume was likely wiped. Retrieval "
            "would silently abstain on everything. Refusing to start; restore the "
            "CHROMA_PERSIST_DIR volume or re-ingest."
        )


async def sweep_stranded_research_tasks(db: AsyncSession) -> int:
    """BEST-EFFORT: mark RUNNING research tasks FAILED (orphans of a restart).

    The only write in startup, so it owns the only commit. Boot-only + single
    instance means every RUNNING row is stranded (nothing is running yet).
    """
    swept = await research_repo.sweep_running_tasks(db, _STRANDED_REASON)
    await db.commit()
    if swept:
        log.info("stranded_research_tasks_swept", count=swept)
    return swept
