"""Research-task database queries."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ResearchTask, ResearchTaskStatus


async def create_task(
    db: AsyncSession, user_id: uuid.UUID, topic: str, k: int | None
) -> ResearchTask:
    task = ResearchTask(user_id=user_id, topic=topic, k=k)
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: uuid.UUID) -> ResearchTask | None:
    return await db.get(ResearchTask, task_id)


async def get_user_task(
    db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID
) -> ResearchTask | None:
    task = await db.get(ResearchTask, task_id)
    if task is None or task.user_id != user_id:
        return None
    return task


async def list_user_tasks(db: AsyncSession, user_id: uuid.UUID) -> list[ResearchTask]:
    result = await db.execute(
        select(ResearchTask)
        .where(ResearchTask.user_id == user_id)
        .order_by(ResearchTask.created_at.desc())
    )
    return list(result.scalars().all())


async def set_task_running(db: AsyncSession, task: ResearchTask) -> None:
    task.status = ResearchTaskStatus.RUNNING
    await db.flush()


async def set_task_completed(
    db: AsyncSession, task: ResearchTask, result: dict
) -> None:
    task.status = ResearchTaskStatus.COMPLETED
    task.result = result
    await db.flush()


async def set_task_failed(db: AsyncSession, task: ResearchTask, error: str) -> None:
    task.status = ResearchTaskStatus.FAILED
    task.error = error
    await db.flush()
