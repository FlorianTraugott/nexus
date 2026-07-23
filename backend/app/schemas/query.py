"""Query schemas: the question in, the grounded answer + citations out."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    # Optional override; the endpoint also enforces a configurable upper bound.
    k: int | None = Field(default=None, gt=0)
    # When set, the turn is persisted to this conversation (validated as the
    # caller's). Absent means the query is stateless — today's exact behaviour.
    conversation_id: uuid.UUID | None = None


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
    # The standalone question retrieval actually used, when the rewrite step ran.
    # NON-NULL whenever the step ran — INCLUDING when the model returned the
    # question unchanged (already standalone) — and NULL only when no step ran at
    # all (no conversation_id, or an empty-history first turn). This keeps two
    # genuinely different events distinct: "the rewrite never fired" vs "it fired
    # and decided no change was needed". Collapsing them into one null would hide,
    # from 9B.4, whether a badly-retrieving follow-up was ever rewritten at all.
    # The UI can still show "searched for: ..." only when it differs from the
    # question (it has both strings); that display concern is recoverable, the
    # did-it-run signal is not once dropped.
    rewritten_question: str | None = None


# --- Streaming (SSE) events for POST /query/stream ---
# Each is emitted as one `data: <json>\n\n` frame. `type` is a discriminant so the
# client can switch on it; the sequence is metadata -> (abstained | token* done).
# A terminal `error` may replace `done` if the model stream fails mid-flight.


class StreamMetadata(BaseModel):
    """First frame: citations + rewritten_question, known before generation."""

    type: Literal["metadata"] = "metadata"
    citations: list[Citation]
    rewritten_question: str | None = None


class StreamToken(BaseModel):
    """One answer delta as it arrives from the model."""

    type: Literal["token"] = "token"
    text: str


class StreamDone(BaseModel):
    """Terminal frame of a successful streamed answer."""

    type: Literal["done"] = "done"


class StreamAbstained(BaseModel):
    """Terminal frame when the gate abstained: the fixed answer, no tokens."""

    type: Literal["abstained"] = "abstained"
    answer: str


class StreamError(BaseModel):
    """Terminal frame when the model stream failed after tokens may have flushed."""

    type: Literal["error"] = "error"
    message: str
