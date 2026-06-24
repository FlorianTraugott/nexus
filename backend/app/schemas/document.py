"""Document schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import DocumentSourceType, DocumentStatus


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    source_type: DocumentSourceType
    status: DocumentStatus
    chunk_count: int
    created_at: datetime
