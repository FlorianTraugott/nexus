"""Background ingestion: turn an uploaded file into chunks and images."""

import asyncio
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import (
    Document,
    DocumentChunk,
    DocumentImage,
    DocumentSourceType,
    DocumentStatus,
)
from app.db.repositories import document as document_repo
from app.db.session import AsyncSessionLocal
from app.services import images as image_service
from app.services import parser, storage, vision
from app.services.chunker import chunk_text
from app.services.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.vector_store import (
    VectorStore,
    get_image_vector_store,
    get_vector_store,
)

log = get_logger(__name__)


async def ingest_document(
    document_id: uuid.UUID, *, include_images: bool = True
) -> None:
    """Entry point for the background task; owns its own session."""
    async with AsyncSessionLocal() as session:
        await run_ingestion(session, document_id, include_images=include_images)


async def run_ingestion(
    session: AsyncSession,
    document_id: uuid.UUID,
    embedder: EmbeddingProvider | None = None,
    store: VectorStore | None = None,
    image_store: VectorStore | None = None,
    *,
    include_images: bool = True,
) -> None:
    document = await document_repo.get_document(session, document_id)
    if document is None:
        return

    # Resolve providers lazily so callers (and tests) can inject fakes.
    embedder = embedder or get_embedding_provider()
    store = store or get_vector_store()
    image_store = image_store or get_image_vector_store()

    document.status = DocumentStatus.PROCESSING
    await session.commit()

    settings = get_settings()
    path = storage.document_path(document.id, document.filename)
    try:
        # Parsing is CPU-bound, so keep it off the event loop.
        text = await asyncio.to_thread(parser.extract_text, path, document.source_type)
        chunks = chunk_text(text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
        chunk_rows = await document_repo.replace_chunks(session, document.id, chunks)
        await _index_chunks(store, embedder, document, chunk_rows)

        # include_images=False is the text-only re-ingest (eval re-chunking):
        # chunk parameters have ZERO effect on images — they are extracted per
        # page and indexed in the separate image collection — so a re-chunk must
        # not re-extract, re-caption (non-deterministic LLM output), or re-index
        # them. Existing image rows and their vectors stay exactly as they are.
        if include_images and document.source_type == DocumentSourceType.PDF:
            extracted = await asyncio.to_thread(
                image_service.extract_images, path, storage.image_dir(document.id)
            )
            image_rows = await document_repo.replace_images(
                session,
                document.id,
                [
                    (img.page_number, img.image_index, str(img.path))
                    for img in extracted
                ],
            )
            captioned = await _caption_images(session, document.id, image_rows)
            await _index_images(image_store, embedder, document, captioned)

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


async def _caption_images(
    session: AsyncSession,
    document_id: uuid.UUID,
    image_rows: list[DocumentImage],
) -> list[tuple[DocumentImage, str]]:
    """Caption each extracted image for search, persisting captions best-effort.

    Broad ``except Exception`` by design — a deliberate deviation from the
    narrow-catch convention used for web search. Captioning has no dedicated
    operational error class (the OpenAI SDK, PIL decode, and disk-read failures
    share no base), and it is non-load-bearing: an ingest whose text indexed fine
    must never fail because one image could not be captioned. So each image is
    isolated — on failure we log and continue, leaving that caption NULL.

    Returns the (image, caption) pairs that were captioned so the caller can
    index them without re-reading the rows; NULL-caption images (junk-filtered,
    NO_CONTENT, or failed) are omitted, since they have nothing to embed.
    """
    captioned: list[tuple[DocumentImage, str]] = []
    for row in image_rows:
        try:
            caption = await vision.caption_image(Path(row.storage_path))
            if caption is not None:
                await document_repo.set_image_caption(session, row.id, caption)
                captioned.append((row, caption))
        except Exception:
            log.warning(
                "image_caption_failed",
                document_id=str(document_id),
                image=row.storage_path,
            )
    return captioned


async def index_captioned_images(
    store: VectorStore,
    embedder: EmbeddingProvider,
    document: Document,
    captioned: list[tuple[DocumentImage, str]],
) -> None:
    """Embed image captions and upsert them into the image collection.

    Deliberately does NOT delete first: this is the additive add-path, reused by
    both ingest (which clears separately, in _index_images) and the backfill
    (which must never wipe a document's already-indexed images). VectorStore.add
    is an upsert, so re-adding the same id is idempotent.

    user_id in the metadata comes from the image's parent document — the scoping
    key retrieval filters on. It must always be that document's owner.
    """
    if not captioned:
        return
    captions = [caption for _, caption in captioned]
    embeddings = await embedder.embed_texts(captions)
    await asyncio.to_thread(
        store.add,
        [str(image.id) for image, _ in captioned],
        embeddings,
        captions,
        [
            {
                "document_id": str(document.id),
                "user_id": str(document.user_id),
                "image_id": str(image.id),
                "page_number": image.page_number,
            }
            for image, _ in captioned
        ],
    )


async def _index_images(
    store: VectorStore,
    embedder: EmbeddingProvider,
    document: Document,
    captioned: list[tuple[DocumentImage, str]],
) -> None:
    """Embed image captions and (re)index them in the separate image collection.

    Kept entirely off the text path (its own store, never _index_chunks). Broad
    ``except Exception`` by design and best-effort: image indexing is
    non-load-bearing, so an ingest whose text indexed fine must still reach
    COMPLETED if the embed or add fails. Clearing first keeps the collection
    consistent with the freshly captioned rows on every re-ingestion.
    """
    try:
        # Chroma's client is synchronous, so run it off the event loop.
        await asyncio.to_thread(store.delete_by_document, document.id)
        await index_captioned_images(store, embedder, document, captioned)
    except Exception:
        log.warning("image_indexing_failed", document_id=str(document.id))


async def _index_chunks(
    store: VectorStore,
    embedder: EmbeddingProvider,
    document: Document,
    chunk_rows: list[DocumentChunk],
) -> None:
    """Embed a document's chunks and (re)index them in the vector store.

    Clearing first keeps the store consistent with the freshly inserted rows,
    whose ids change on every re-ingestion.
    """
    # Chroma's client is synchronous, so run it off the event loop.
    await asyncio.to_thread(store.delete_by_document, document.id)
    if not chunk_rows:
        return
    embeddings = await embedder.embed_texts([chunk.content for chunk in chunk_rows])
    await asyncio.to_thread(
        store.add,
        [str(chunk.id) for chunk in chunk_rows],
        embeddings,
        [chunk.content for chunk in chunk_rows],
        [
            {
                "document_id": str(document.id),
                "user_id": str(document.user_id),
                "chunk_index": chunk.chunk_index,
            }
            for chunk in chunk_rows
        ],
    )
