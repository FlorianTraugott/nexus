"""Vision endpoint: answer a question about one document's extracted images."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.vision import (
    ImageSearchRequest,
    ImageSearchResponse,
    ImageSource,
    VisionAnswerResponse,
    VisionQuestionRequest,
)
from app.services.retrieval import PREVIEW_CHARS
from app.services.vision import (
    DocumentNotFoundError,
    NoDocumentImagesError,
    answer_document_images,
    search_document_images,
)

router = APIRouter(prefix="/vision", tags=["vision"])


# Declared before /{document_id} so "search" is not captured as a document_id.
@router.post("/search", response_model=ImageSearchResponse)
async def search_images(
    payload: ImageSearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ImageSearchResponse:
    max_k = get_settings().RAG_MAX_TOP_K
    if payload.k is not None and payload.k > max_k:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"k must not exceed {max_k}",
        )

    result = await search_document_images(
        db=db,
        user_id=current_user.id,
        question=payload.question,
        k=payload.k,
    )
    return ImageSearchResponse(
        answer=result.answer,
        sources=[
            ImageSource(
                image_id=match.image.id,
                document_id=match.image.document_id,
                page_number=match.image.page_number,
                distance=match.distance,
                caption_preview=(match.image.caption or "")[:PREVIEW_CHARS],
            )
            for match in result.sources
        ],
    )


@router.post("/{document_id}", response_model=VisionAnswerResponse)
async def ask_document_images(
    document_id: uuid.UUID,
    payload: VisionQuestionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VisionAnswerResponse:
    try:
        result = await answer_document_images(
            db=db,
            document_id=document_id,
            user_id=current_user.id,
            question=payload.question,
        )
    except DocumentNotFoundError:
        # Translate the domain error to a 404 without leaking the traceback.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from None
    except NoDocumentImagesError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Document has no images to answer from",
        ) from None
    return VisionAnswerResponse(
        answer=result.answer,
        images_used=result.images_used,
        images_total=result.images_total,
    )
