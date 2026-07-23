"""Conversation management endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Conversation, User
from app.db.repositories import conversation as conversation_repo
from app.db.session import get_db
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Conversation:
    conversation = await conversation_repo.create_conversation(
        db, current_user.id, payload.title
    )
    await db.commit()
    return conversation


@router.get("", response_model=list[ConversationRead])
async def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Conversation]:
    return await conversation_repo.list_user_conversations(db, current_user.id)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Conversation:
    conversation = await conversation_repo.get_user_conversation_with_messages(
        db, conversation_id, current_user.id
    )
    # Same 404 for missing and other-user, so a probe can't distinguish them.
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return conversation


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    conversation = await conversation_repo.get_user_conversation(
        db, conversation_id, current_user.id
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    await conversation_repo.delete_conversation(db, conversation)
    await db.commit()
