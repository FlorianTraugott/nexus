"""Query endpoint: retrieve the user's relevant chunks, then answer from them."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import MessageRole, User
from app.db.repositories import conversation as conversation_repo
from app.db.session import get_db
from app.schemas.query import (
    Citation,
    QueryRequest,
    QueryResponse,
    StreamAbstained,
    StreamDone,
    StreamError,
    StreamMetadata,
    StreamToken,
)
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
log = get_logger(__name__)

# Citations carry a snippet for display, not the full chunk text.
_PREVIEW_CHARS = 280

# Returned instead of a generated answer when nothing relevant was retrieved.
_NO_ANSWER = "I could not find anything relevant in your documents to answer that."


def _sse(event: BaseModel) -> str:
    """Encode one typed event as an SSE frame: `data: <json>\\n\\n`."""
    return f"data: {event.model_dump_json()}\n\n"


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
    #
    # History is loaded ONCE, at the larger MEMORY_HISTORY_TURNS limit: the rewrite
    # slices the last REWRITE_HISTORY_TURNS off the tail, and the full list frames
    # the generation prompt further down. memory_history stays [] when there is no
    # conversation, so build_prompt below receives no history and its output is
    # byte-identical to today (keeping the faithfulness baseline comparable).
    retrieval_question = payload.question
    rewritten_question: str | None = None
    memory_history: list[tuple[str, str]] = []
    if payload.conversation_id is not None:
        settings = get_settings()
        messages = await conversation_repo.list_recent_messages(
            db, payload.conversation_id, settings.MEMORY_HISTORY_TURNS
        )
        memory_history = [(m.role.value, m.content) for m in messages]
        if memory_history:
            rewritten_question = await rewrite_query(
                payload.question,
                memory_history[-settings.REWRITE_HISTORY_TURNS :],
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
        # Prior turns frame the answer (resolve pronouns/references) but never
        # ground it; build_prompt's system clause enforces that. None when there is
        # no conversation, so this call matches today's exactly.
        system, prompt = build_prompt(
            payload.question,
            [r.chunk.content for r in results],
            history=memory_history or None,
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


@router.post("/stream")
async def query_stream(
    payload: QueryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    embedder: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    store: Annotated[VectorStore, Depends(get_vector_store)],
    generator: Annotated[GenerationProvider, Depends(get_generation_provider)],
) -> StreamingResponse:
    """Stream the grounded answer token-by-token over SSE.

    Sibling to POST /query: reproduces its retrieve -> gate pipeline EXACTLY, then
    STREAMS the generation instead of buffering it. /query is untouched, so the
    eval baselines that measure it stay comparable. The prep (ownership, rewrite,
    retrieval, gate) runs BEFORE the StreamingResponse so k>max (422) and bad
    conversation_id (404) are real HTTP errors, not SSE frames on a 200 body. The
    SSE sequence is: metadata -> (abstained | token* done | token* error).
    """
    settings = get_settings()
    max_k = settings.RAG_MAX_TOP_K
    if payload.k is not None and payload.k > max_k:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"k must not exceed {max_k}",
        )

    if payload.conversation_id is not None:
        conversation = await conversation_repo.get_user_conversation(
            db, payload.conversation_id, current_user.id
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

    # History load + rewrite — identical to /query (see that handler for the why).
    retrieval_question = payload.question
    rewritten_question: str | None = None
    memory_history: list[tuple[str, str]] = []
    if payload.conversation_id is not None:
        messages = await conversation_repo.list_recent_messages(
            db, payload.conversation_id, settings.MEMORY_HISTORY_TURNS
        )
        memory_history = [(m.role.value, m.content) for m in messages]
        if memory_history:
            rewritten_question = await rewrite_query(
                payload.question,
                memory_history[-settings.REWRITE_HISTORY_TURNS :],
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

    # Same gate as /query: min() over distances, abstain on empty. Everything the
    # metadata frame needs (citations, abstention decision, the prompt) is known
    # before a single token streams.
    abstained = not results or not passes_distance_gate(
        min(r.distance for r in results), settings.RAG_MAX_DISTANCE
    )
    if abstained:
        citations: list[Citation] = []
        system = prompt = ""
    else:
        system, prompt = build_prompt(
            payload.question,
            [r.chunk.content for r in results],
            history=memory_history or None,
        )
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

    async def event_stream() -> AsyncIterator[str]:
        # Citations are the retrieved chunks — known before generation.
        yield _sse(
            StreamMetadata(citations=citations, rewritten_question=rewritten_question)
        )

        if abstained:
            # Same as sync abstention: no generator call, no token frames.
            yield _sse(StreamAbstained(answer=_NO_ANSWER))
            answer = _NO_ANSWER
        else:
            parts: list[str] = []
            try:
                async for delta in generator.generate_stream(system, prompt):
                    parts.append(delta)
                    yield _sse(StreamToken(text=delta))
            except Exception as exc:
                # The response is already 200 with headers flushed, so the only
                # honest failure signal is a terminal error frame. Persist NOTHING:
                # a half-streamed turn would corrupt the history 9B.3 reads back.
                # (A client disconnect raises CancelledError/GeneratorExit, which
                # are BaseException — not caught here — so it also skips persistence.)
                log.warning("query_stream_generation_failed", error=str(exc))
                yield _sse(StreamError(message="generation failed"))
                return
            answer = "".join(parts)
            yield _sse(StreamDone())

        # Reached only on a fully successful stream (token error returned above;
        # disconnect cancelled the generator before here). Persist the SAME turn
        # /query would, via the SAME _persist_turn — abstention turns included.
        if payload.conversation_id is not None:
            await _persist_turn(
                db, payload.conversation_id, payload.question, answer, citations
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        # no-cache: SSE must never be cached. X-Accel-Buffering: no tells a reverse
        # proxy (nginx, Part 12) not to buffer, which would defeat token streaming.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
