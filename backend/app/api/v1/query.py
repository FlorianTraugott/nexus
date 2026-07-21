"""Query endpoint: retrieve the user's relevant chunks, then answer from them."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import MessageRole, User
from app.db.repositories import conversation as conversation_repo
from app.db.session import get_db
from app.schemas.query import Citation, QueryRequest, QueryResponse
from app.services.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.generation import (
    GenerationProvider,
    build_prompt,
    get_generation_provider,
)
from app.services.query_rewrite import rewrite_query
from app.services.retrieval import retrieve
from app.services.retrieval_policy import passes_distance_gate
from app.services.vector_store import VectorStore, get_vector_store

router = APIRouter(prefix="/query", tags=["query"])

# Citations carry a snippet for display, not the full chunk text.
_PREVIEW_CHARS = 280

# Returned instead of a generated answer when nothing relevant was retrieved.
_NO_ANSWER = "I could not find anything relevant in your documents to answer that."


async def _persist_turn(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    question: str,
    answer: str,
    citations: list[Citation],
) -> None:
    """Persist a user question + assistant answer as one atomic turn.

    CRITICAL, not best-effort: a silently unsaved turn would corrupt the history
    that 9B.3 reads back as prompt context, so a write failure must fail the
    request. Both rows are added to the request session and committed ONCE, so a
    turn is both messages or neither (never an orphaned question). The abstention
    answer is persisted too — it is a real turn and the transcript must not lie.
    """
    await conversation_repo.add_message(db, conversation_id, MessageRole.USER, question)
    await conversation_repo.add_message(
        db,
        conversation_id,
        MessageRole.ASSISTANT,
        answer,
        citations=[c.model_dump(mode="json") for c in citations],
    )
    await db.commit()


@router.post("", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    embedder: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    store: Annotated[VectorStore, Depends(get_vector_store)],
    generator: Annotated[GenerationProvider, Depends(get_generation_provider)],
) -> QueryResponse:
    max_k = get_settings().RAG_MAX_TOP_K
    if payload.k is not None and payload.k > max_k:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"k must not exceed {max_k}",
        )

    # Validate conversation ownership BEFORE retrieve() so a bad id costs no
    # embedding or generation call. Same 404 wording as the conversations router.
    if payload.conversation_id is not None:
        conversation = await conversation_repo.get_user_conversation(
            db, payload.conversation_id, current_user.id
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

    # Rewrite a conversational follow-up into a standalone question BEFORE
    # retrieval, using recent history ONLY to disambiguate (never as grounding).
    # The step runs only for a conversation that already has messages; absent
    # conversation_id or a first turn is exactly today's behaviour — no history
    # load, no LLM call — so the eval-harness path and its baselines are untouched.
    # The REWRITTEN question drives retrieval only; the ORIGINAL question is what
    # the LLM answers and what the transcript records (the user asked what they
    # asked — the rewrite fixes embedding, not intent).
    retrieval_question = payload.question
    rewritten_question: str | None = None
    if payload.conversation_id is not None:
        history = await conversation_repo.list_recent_messages(
            db, payload.conversation_id, get_settings().REWRITE_HISTORY_TURNS
        )
        if history:
            rewritten_question = await rewrite_query(
                payload.question,
                [(message.role.value, message.content) for message in history],
                generator=generator,
            )
            retrieval_question = rewritten_question

    results = await retrieve(
        db,
        retrieval_question,
        current_user.id,
        k=payload.k,
        embedder=embedder,
        store=store,
    )

    # Abstain before spending a generation call on irrelevant context. min()
    # rather than results[0]: this gate exists to prevent confabulation, so it
    # must not depend on retrieve()'s ascending-order guarantee holding — if that
    # ever changed, results[0] would misfire toward answering when it should
    # abstain, the dangerous direction. min() is cheap insurance on a k-sized list.
    max_distance = get_settings().RAG_MAX_DISTANCE
    if not results or not passes_distance_gate(
        min(r.distance for r in results), max_distance
    ):
        answer = _NO_ANSWER
        citations: list[Citation] = []
    else:
        system, prompt = build_prompt(
            payload.question, [r.chunk.content for r in results]
        )
        answer = await generator.generate(system, prompt)
        citations = [
            Citation(
                chunk_id=r.chunk.id,
                document_id=r.chunk.document_id,
                chunk_index=r.chunk.chunk_index,
                distance=r.distance,
                content_preview=r.chunk.content[:_PREVIEW_CHARS],
            )
            for r in results
        ]

    if payload.conversation_id is not None:
        await _persist_turn(
            db, payload.conversation_id, payload.question, answer, citations
        )

    return QueryResponse(
        answer=answer, citations=citations, rewritten_question=rewritten_question
    )
