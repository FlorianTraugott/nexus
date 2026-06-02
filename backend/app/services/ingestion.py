"""Background ingestion: turn an uploaded file into chunks and images."""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import DocumentSourceType, DocumentStatus
from app.db.repositories import document as document_repo
from app.db.session import AsyncSessionLocal
from app.services import images as image_service
from app.services import parser, storage
from app.services.chunker import chunk_text

log = get_logger(__name__)


async def ingest_document(document_id: uuid.UUID) -> None:
    """Entry point for the background task; owns its own session."""
    async with AsyncSessionLocal() as session:
        await run_ingestion(session, document_id)


async def run_ingestion(session: AsyncSession, document_id: uuid.UUID) -> None:
    document = await document_repo.get_document(session, document_id)
    if document is None:
        return

    document.status = DocumentStatus.PROCESSING
    await session.commit()

    settings = get_settings()
    path = storage.document_path(document.id, document.filename)
    try:
        # Parsing is CPU-bound, so keep it off the event loop.
        text = await asyncio.to_thread(parser.extract_text, path, document.source_type)
        chunks = chunk_text(text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
        await document_repo.replace_chunks(session, document.id, chunks)

        if document.source_type == DocumentSourceType.PDF:
            extracted = await asyncio.to_thread(
                image_service.extract_images, path, storage.image_dir(document.id)
            )
            await document_repo.replace_images(
                session,
                document.id,
                [
                    (img.page_number, img.image_index, str(img.path))
                    for img in extracted
                ],
            )

        document.chunk_count = len(chunks)
        document.status = DocumentStatus.COMPLETED
        await session.commit()
    except Exception:
        log.exception("ingestion_failed", document_id=str(document_id))
        await session.rollback()
        document = await document_repo.get_document(session, document_id)
        if document is not None:
            document.status = DocumentStatus.FAILED
            await session.commit()
