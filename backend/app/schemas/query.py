"""Query schemas: the question in, the grounded answer + citations out."""

import uuid

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    # Optional override; the endpoint also enforces a configurable upper bound.
    k: int | None = Field(default=None, gt=0)


class Citation(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    # Chroma cosine distance: LOWER is more relevant, not a similarity score.
    distance: float
    content_preview: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
