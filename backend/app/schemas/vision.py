"""Vision schemas: a question about a document's images in, the answer out."""

from pydantic import BaseModel, Field


class VisionQuestionRequest(BaseModel):
    question: str = Field(min_length=1)


class VisionAnswerResponse(BaseModel):
    answer: str
    images_used: int
    images_total: int
