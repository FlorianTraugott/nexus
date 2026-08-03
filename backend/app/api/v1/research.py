"""Research endpoints: schedule an async run over the user's corpus, then poll.

POST creates a persisted task and returns immediately (202); a background task
runs the multi-agent pipeline; GET polls for status and, once done, the result.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.middleware import limiter, research_rate_limit, user_scoped_key
from app.db.models import User
from app.db.repositories import research as research_repo
from app.db.session import get_db
from app.schemas.research import (
    ResearchRequest,
    ResearchResponse,
    ResearchTaskCreated,
    ResearchTaskRead,
)
from app.services.research_runner import run_research_task

router = APIRouter(prefix="/research", tags=["research"])

ResearchRunner = Callable[[uuid.UUID], Awaitable[None]]


def get_research_runner() -> ResearchRunner:
    # Indirection so tests can swap in a runner bound to their session/providers,
    # mirroring get_ingestion_runner.
    return run_research_task


@router.post(
    "", response_model=ResearchTaskCreated, status_code=status.HTTP_202_ACCEPTED
)
@limiter.limit(research_rate_limit, key_func=user_scoped_key)
async def create_research_task(
    request: Request,
    payload: ResearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
    runner: Annotated[ResearchRunner, Depends(get_research_runner)],
) -> ResearchTaskCreated:
    max_k = get_settings().RAG_MAX_TOP_K
    if payload.k is not None and payload.k > max_k:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"k must not exceed {max_k}",
        )

    # user_id from the token, never the payload, so a run only sees its own corpus.
    task = await research_repo.create_task(
        db, current_user.id, payload.topic, payload.k
    )
    await db.commit()

    background_tasks.add_task(runner, task.id)
    return ResearchTaskCreated(task_id=task.id, status=task.status)


@router.get("/{task_id}", response_model=ResearchTaskRead)
async def get_research_task(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResearchTaskRead:
    task = await research_repo.get_user_task(db, task_id, current_user.id)
    # Same 404 for missing and other-user, so a probe can't distinguish them.
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Research task not found"
        )

    result = (
        ResearchResponse.model_validate(task.result)
        if task.result is not None
        else None
    )
    return ResearchTaskRead(
        task_id=task.id,
        topic=task.topic,
        status=task.status,
        result=result,
        error=task.error,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
