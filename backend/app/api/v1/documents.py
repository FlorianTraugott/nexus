"""Document management endpoints."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import Document, DocumentSourceType, User
from app.db.repositories import document as document_repo
from app.db.session import get_db
from app.schemas.document import DocumentRead
from app.services import storage
from app.services.ingestion import ingest_document
from app.services.vector_store import (
    VectorStore,
    get_image_vector_store,
    get_vector_store,
)

router = APIRouter(prefix="/documents", tags=["documents"])

IngestionRunner = Callable[[uuid.UUID], Awaitable[None]]

_SUFFIX_TO_SOURCE = {
    ".pdf": DocumentSourceType.PDF,
    ".txt": DocumentSourceType.TEXT,
    ".text": DocumentSourceType.TEXT,
    ".md": DocumentSourceType.TEXT,
    ".markdown": DocumentSourceType.TEXT,
}


def get_ingestion_runner() -> IngestionRunner:
    # Indirection so tests can swap in a no-op instead of the real pipeline.
    return ingest_document


def _resolve_source_type(filename: str) -> DocumentSourceType:
    suffix = Path(filename).suffix.lower()
    source_type = _SUFFIX_TO_SOURCE.get(suffix)
    if source_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF and text files are supported",
        )
    return source_type


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
    ingest: Annotated[IngestionRunner, Depends(get_ingestion_runner)],
) -> Document:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A filename is required"
        )
    source_type = _resolve_source_type(file.filename)

    content = await file.read()
    if len(content) > get_settings().max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the maximum allowed size",
        )

    document = await document_repo.create_document(
        db, current_user.id, file.filename, source_type
    )
    await storage.save_file(storage.document_path(document.id, file.filename), content)
    await db.commit()

    background_tasks.add_task(ingest, document.id)
    return document


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Document]:
    return await document_repo.list_user_documents(db, current_user.id)


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Document:
    document = await document_repo.get_user_document(db, document_id, current_user.id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    store: Annotated[VectorStore, Depends(get_vector_store)],
    image_store: Annotated[VectorStore, Depends(get_image_vector_store)],
) -> None:
    document = await document_repo.get_user_document(db, document_id, current_user.id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    filename = document.filename
    await document_repo.delete_document(db, document)
    await db.commit()
    # Vectors and files are cleaned up after the row is gone; an orphaned row
    # would be worse than an orphaned vector or file. Image vectors live in their
    # own collection, so they need a second delete or they poison future top-k.
    await asyncio.to_thread(store.delete_by_document, document_id)
    await asyncio.to_thread(image_store.delete_by_document, document_id)
    storage.delete_document_files(document_id, filename)
