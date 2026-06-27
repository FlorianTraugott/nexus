"""Research-pipeline schemas: the typed state and each agent's structured output.

Pure types — no I/O, no providers, no DB. Every agent in the pipeline returns
one of the *Findings/Summary/Report models below (validated, never free text),
and ResearchState threads them together as the pipeline advances through the
ResearchStage steps.
"""

import enum
import uuid

from pydantic import BaseModel, Field


class ResearchStage(enum.StrEnum):
    """The ordered steps a research run moves through."""

    WEB_SEARCH = "web_search"
    KB_QUERY = "kb_query"
    SUMMARISE = "summarise"
    REPORT = "report"
    DONE = "done"


class WebSearchHit(BaseModel):
    """One result from the web-search provider."""

    title: str
    url: str
    snippet: str
    # Provider relevance score when available; not all providers return one.
    score: float | None = None


class WebSearchFindings(BaseModel):
    """Web-search agent output: the query and its hits (possibly empty)."""

    query: str
    hits: list[WebSearchHit]


class KBFinding(BaseModel):
    """One retrieved chunk from the user's own corpus.

    Sibling of the query endpoint's Citation so the research module does not
    couple to that response type; shaped to receive a RetrievedChunk.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    # Chroma cosine distance: LOWER is more relevant, not a similarity score.
    distance: float
    content_preview: str


class KBFindings(BaseModel):
    """Knowledge-base agent output: the query and its findings (possibly empty)."""

    query: str
    findings: list[KBFinding]


class Summary(BaseModel):
    """Summariser output: a structured digest, not prose to regex later."""

    key_points: list[str]
    abstract: str = Field(min_length=1)


class ReportSection(BaseModel):
    """One section of the final report."""

    heading: str = Field(min_length=1)
    body: str = Field(min_length=1)


class ResearchReport(BaseModel):
    """Report-writer output: structured sections plus a rendered markdown body."""

    title: str = Field(min_length=1)
    sections: list[ReportSection]
    markdown: str = Field(min_length=1)


class ResearchRequest(BaseModel):
    """The research question in; user_id comes from the token, never the body."""

    topic: str = Field(min_length=1)
    # Optional override; the endpoint also enforces a configurable upper bound.
    k: int | None = Field(default=None, gt=0)


class ResearchResponse(BaseModel):
    """The completed run out: the state minus user_id, reusing the nested models.

    Exposes the report plus its supporting evidence (web hits + KB findings) and
    any warnings/error, so the client inspects one resource. A recorded pipeline
    failure rides here as a populated `error` with `report` null, not a 5xx.
    """

    topic: str
    stage: ResearchStage
    web: WebSearchFindings | None
    kb: KBFindings | None
    summary: Summary | None
    report: ResearchReport | None
    warnings: list[str]
    error: str | None


class ResearchState(BaseModel):
    """The state threaded through the pipeline, filled in stage by stage."""

    topic: str = Field(min_length=1)
    user_id: uuid.UUID
    # Optional retrieval override for the KB-query step; the endpoint also
    # enforces an upper bound, mirroring the query endpoint.
    k: int | None = Field(default=None, gt=0)

    stage: ResearchStage = ResearchStage.WEB_SEARCH
    web: WebSearchFindings | None = None
    kb: KBFindings | None = None
    summary: Summary | None = None
    report: ResearchReport | None = None
    # Non-fatal degradations (e.g. web search unavailable): the run continues
    # and the status endpoint surfaces these. Reserve `error` for failures that
    # make the whole run meaningless.
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
