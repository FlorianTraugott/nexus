"""Conversation and message schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import MessageRole
from app.schemas.query import Citation


class ConversationCreate(BaseModel):
    # Optional; the model default ("New conversation") applies when omitted.
    title: str | None = Field(default=None, min_length=1, max_length=255)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    # Present on assistant turns; the stored JSON validates back into Citations.
    citations: list[Citation] | None
    position: int
    created_at: datetime


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    """A conversation plus its ordered messages (GET /conversations/{id})."""

    messages: list[MessageRead]
