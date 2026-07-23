"""Core ORM models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ResearchTaskStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentSourceType(enum.StrEnum):
    PDF = "pdf"
    TEXT = "text"
    YOUTUBE = "youtube"
    WEB = "web"


class DocumentStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class Conversation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(255), default="New conversation", nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        # Order by the explicit per-conversation ordinal, not created_at: both
        # messages of a turn commit in one transaction and Postgres now() returns
        # transaction-start time, so they share created_at and would sort
        # non-deterministically.
        order_by="Message.position",
    )


class Message(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    # Position is the sole source of intra-conversation order. The UNIQUE
    # constraint makes a duplicate position raise IntegrityError immediately
    # rather than silently reintroducing the non-deterministic ordering this
    # column exists to fix; it also serves as the index for ORDER BY position.
    __table_args__ = (UniqueConstraint("conversation_id", "position"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, native_enum=False, length=20), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 0-based ordinal within the conversation; assigned as max(position)+1.
    position: Mapped[int] = mapped_column(nullable=False)
    # Assistant-message citations as JSON (Citation.model_dump); NULL for user
    # messages and [] for an abstention turn (a real turn with no sources).
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Document(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[DocumentSourceType] = mapped_column(
        Enum(DocumentSourceType, native_enum=False, length=20), nullable=False
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False, length=20),
        default=DocumentStatus.PENDING,
        nullable=False,
    )
    chunk_count: Mapped[int] = mapped_column(default=0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    images: Mapped[list["DocumentImage"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ResearchTask(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "research_tasks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional retrieval override captured at request time; the endpoint enforces
    # the RAG_MAX_TOP_K bound before persisting. Stored because the request
    # context is gone by the time the background runner builds ResearchState.
    k: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[ResearchTaskStatus] = mapped_column(
        Enum(ResearchTaskStatus, native_enum=False, length=20),
        default=ResearchTaskStatus.PENDING,
        nullable=False,
    )
    # The serialised ResearchResponse (model_dump(mode="json")); NULL until the
    # run finishes. A recorded PIPELINE failure — the orchestrator setting
    # state.error — is a COMPLETED task carrying that error INSIDE result, which
    # preserves the "a failed run is still the resource" semantics of the old
    # synchronous endpoint. The `error` column below is different: it is reserved
    # for INFRASTRUCTURE failure (the runner itself raised), which sets status
    # FAILED and leaves result NULL. The frontend distinguishes these two.
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentChunk(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # position of this chunk within its document, starting at 0
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")


class DocumentImage(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "document_images"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 0-based page the image was found on
    page_number: Mapped[int] = mapped_column(nullable=False)
    # position within the document, across all pages, starting at 0
    image_index: Mapped[int] = mapped_column(nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # vision-generated description that makes the image semantically findable;
    # NULL means the image has not been captioned yet
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="images")
