"""Vision schemas: a question about a document's images in, the answer out."""

import uuid

from pydantic import BaseModel, Field


class VisionQuestionRequest(BaseModel):
    question: str = Field(min_length=1)


class VisionAnswerResponse(BaseModel):
    answer: str
    images_used: int
    images_total: int


class ImageSearchRequest(BaseModel):
    question: str = Field(min_length=1)
    # Optional override; the endpoint also enforces a configurable upper bound.
    k: int | None = Field(default=None, gt=0)


class ImageSource(BaseModel):
    image_id: uuid.UUID
    document_id: uuid.UUID
    page_number: int
    # Chroma cosine distance: LOWER is more relevant, not a similarity score.
    distance: float
    caption_preview: str


class ImageSearchResponse(BaseModel):
    answer: str
    sources: list[ImageSource]
