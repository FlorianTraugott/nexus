"""Conversation and message database queries."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Conversation, Message, MessageRole


async def create_conversation(
    db: AsyncSession, user_id: uuid.UUID, title: str | None = None
) -> Conversation:
    # Let the model default supply the title when the caller omits one.
    conversation = (
        Conversation(user_id=user_id, title=title)
        if title is not None
        else Conversation(user_id=user_id)
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def get_user_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> Conversation | None:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        return None
    return conversation


async def get_user_conversation_with_messages(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> Conversation | None:
    """Fetch one of a user's conversations with its messages eager-loaded.

    Messages are ordered by the relationship's order_by (position). Eager loading
    avoids a detached lazy-load when the response is serialised.
    """
    stmt = (
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .options(selectinload(Conversation.messages))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_user_conversations(
    db: AsyncSession, user_id: uuid.UUID
) -> list[Conversation]:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_conversation(db: AsyncSession, conversation: Conversation) -> None:
    await db.delete(conversation)


async def add_message(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    role: MessageRole,
    content: str,
    citations: list | None = None,
) -> Message:
    """Append a message at the next per-conversation position.

    position = max(existing)+1. Sequential calls in one transaction see each
    other's flushed rows, so a turn's two messages get consecutive positions.
    The UNIQUE (conversation_id, position) constraint turns any collision into a
    loud IntegrityError rather than a silent ordering corruption.
    """
    next_position = (
        await db.execute(
            select(func.coalesce(func.max(Message.position), -1) + 1).where(
                Message.conversation_id == conversation_id
            )
        )
    ).scalar_one()
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        position=next_position,
        citations=citations,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def list_messages(db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.position)
    )
    return list(result.scalars().all())


async def list_recent_messages(
    db: AsyncSession, conversation_id: uuid.UUID, limit: int
) -> list[Message]:
    """Return the last `limit` messages in chronological (ascending) order.

    Fetches newest-first with a LIMIT so a long transcript is not fully loaded,
    then reverses so the caller sees them oldest-to-newest.
    """
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.position.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return rows
