"""Query endpoint: retrieve the user's relevant chunks, then answer from them."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.query import Citation, QueryRequest, QueryResponse
from app.services.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.generation import (
    GenerationProvider,
    build_prompt,
    get_generation_provider,
)
from app.services.retrieval import retrieve
from app.services.retrieval_policy import passes_distance_gate
from app.services.vector_store import VectorStore, get_vector_store

router = APIRouter(prefix="/query", tags=["query"])

# Citations carry a snippet for display, not the full chunk text.
_PREVIEW_CHARS = 280

# Returned instead of a generated answer when nothing relevant was retrieved.
_NO_ANSWER = "I could not find anything relevant in your documents to answer that."


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

    results = await retrieve(
        db,
        payload.question,
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
        return QueryResponse(answer=_NO_ANSWER, citations=[])

    system, prompt = build_prompt(payload.question, [r.chunk.content for r in results])
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
    return QueryResponse(answer=answer, citations=citations)
