"""Research endpoint: run the multi-agent pipeline over the user's own corpus."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import run_research
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.schemas.research import ResearchRequest, ResearchResponse, ResearchState
from app.services.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.generation import GenerationProvider, get_generation_provider
from app.services.search import SearchProvider, get_search_provider
from app.services.vector_store import VectorStore, get_vector_store

router = APIRouter(prefix="/research", tags=["research"])


@router.post("", response_model=ResearchResponse)
async def research(
    payload: ResearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    search: Annotated[SearchProvider, Depends(get_search_provider)],
    embedder: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    store: Annotated[VectorStore, Depends(get_vector_store)],
    generator: Annotated[GenerationProvider, Depends(get_generation_provider)],
) -> ResearchResponse:
    max_k = get_settings().RAG_MAX_TOP_K
    if payload.k is not None and payload.k > max_k:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"k must not exceed {max_k}",
        )

    # user_id from the token, never the payload, so a run only sees its own corpus.
    state = ResearchState(topic=payload.topic, user_id=current_user.id, k=payload.k)
    state = await run_research(
        state,
        db,
        search=search,
        embedder=embedder,
        store=store,
        generator=generator,
    )

    # A recorded pipeline failure is a 200 with `error` set, not a 5xx: the
    # completed run (incl. partial state + warnings) is the resource to inspect.
    return ResearchResponse(
        topic=state.topic,
        stage=state.stage,
        web=state.web,
        kb=state.kb,
        summary=state.summary,
        report=state.report,
        warnings=state.warnings,
        error=state.error,
    )
