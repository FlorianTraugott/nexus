"""Document database queries."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk, DocumentImage, DocumentSourceType


async def create_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    filename: str,
    source_type: DocumentSourceType,
) -> Document:
    document = Document(user_id=user_id, filename=filename, source_type=source_type)
    db.add(document)
    await db.flush()
    await db.refresh(document)
    return document


async def get_document(db: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return await db.get(Document, document_id)


async def get_user_document(
    db: AsyncSession, document_id: uuid.UUID, user_id: uuid.UUID
) -> Document | None:
    document = await db.get(Document, document_id)
    if document is None or document.user_id != user_id:
        return None
    return document


async def list_user_documents(db: AsyncSession, user_id: uuid.UUID) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_document(db: AsyncSession, document: Document) -> None:
    await db.delete(document)


async def get_chunks_by_ids(
    db: AsyncSession, ids: list[uuid.UUID]
) -> list[DocumentChunk]:
    """Fetch chunks by id in one query; rows come back in arbitrary order."""
    if not ids:
        return []
    result = await db.execute(select(DocumentChunk).where(DocumentChunk.id.in_(ids)))
    return list(result.scalars().all())


async def replace_chunks(
    db: AsyncSession, document_id: uuid.UUID, contents: list[str]
) -> list[DocumentChunk]:
    """Replace a document's chunks and return the freshly created rows."""
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )
    chunks = [
        DocumentChunk(document_id=document_id, chunk_index=index, content=content)
        for index, content in enumerate(contents)
    ]
    db.add_all(chunks)
    await db.flush()
    return chunks


async def replace_images(
    db: AsyncSession, document_id: uuid.UUID, images: list[tuple[int, int, str]]
) -> None:
    """Replace a document's images. Each tuple is (page, index, storage_path)."""
    await db.execute(
        delete(DocumentImage).where(DocumentImage.document_id == document_id)
    )
    db.add_all(
        DocumentImage(
            document_id=document_id,
            page_number=page_number,
            image_index=image_index,
            storage_path=storage_path,
        )
        for page_number, image_index, storage_path in images
    )
    await db.flush()
