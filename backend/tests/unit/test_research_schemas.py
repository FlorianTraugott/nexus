"""Tests for the research-pipeline schemas: defaults, validation, round-trip."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.research import (
    KBFinding,
    KBFindings,
    ReportSection,
    ResearchReport,
    ResearchStage,
    ResearchState,
    Summary,
    WebSearchFindings,
    WebSearchHit,
)


def test_stage_is_a_string_enum_in_pipeline_order() -> None:
    assert list(ResearchStage) == [
        ResearchStage.WEB_SEARCH,
        ResearchStage.KB_QUERY,
        ResearchStage.SUMMARISE,
        ResearchStage.REPORT,
        ResearchStage.DONE,
    ]
    # StrEnum: a stage compares and serialises as its plain string value.
    assert ResearchStage.WEB_SEARCH == "web_search"


def test_state_defaults_start_unpopulated_at_first_stage() -> None:
    state = ResearchState(topic="quantum error correction", user_id=uuid.uuid4())

    assert state.stage is ResearchStage.WEB_SEARCH
    assert state.k is None
    assert state.web is None
    assert state.kb is None
    assert state.summary is None
    assert state.report is None
    assert state.warnings == []
    assert state.error is None


def test_state_warnings_default_to_an_independent_list() -> None:
    a = ResearchState(topic="t", user_id=uuid.uuid4())
    b = ResearchState(topic="t", user_id=uuid.uuid4())

    a.warnings.append("web search unavailable")

    # default_factory: each state gets its own list, not a shared default.
    assert a.warnings == ["web search unavailable"]
    assert b.warnings == []


def test_state_requires_topic_and_user_id() -> None:
    with pytest.raises(ValidationError):
        ResearchState(user_id=uuid.uuid4())  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ResearchState(topic="x")  # type: ignore[call-arg]


def test_state_rejects_empty_topic_and_non_positive_k() -> None:
    uid = uuid.uuid4()
    with pytest.raises(ValidationError):
        ResearchState(topic="", user_id=uid)
    with pytest.raises(ValidationError):
        ResearchState(topic="ok", user_id=uid, k=0)


def test_findings_accept_empty_result_lists() -> None:
    assert WebSearchFindings(query="q", hits=[]).hits == []
    assert KBFindings(query="q", findings=[]).findings == []


def test_web_hit_score_is_optional() -> None:
    hit = WebSearchHit(title="t", url="https://example.com", snippet="s")
    assert hit.score is None


def test_structured_outputs_reject_empty_required_text() -> None:
    with pytest.raises(ValidationError):
        Summary(key_points=["a"], abstract="")
    with pytest.raises(ValidationError):
        ReportSection(heading="", body="b")
    with pytest.raises(ValidationError):
        ResearchReport(title="t", sections=[], markdown="")


def test_state_round_trips_through_dump_and_validate() -> None:
    chunk_id, document_id = uuid.uuid4(), uuid.uuid4()
    state = ResearchState(
        topic="ml ops",
        user_id=uuid.uuid4(),
        stage=ResearchStage.DONE,
        web=WebSearchFindings(
            query="ml ops",
            hits=[WebSearchHit(title="t", url="https://e.com", snippet="s", score=0.9)],
        ),
        kb=KBFindings(
            query="ml ops",
            findings=[
                KBFinding(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    chunk_index=3,
                    distance=0.12,
                    content_preview="snippet",
                )
            ],
        ),
        summary=Summary(key_points=["a", "b"], abstract="short abstract"),
        report=ResearchReport(
            title="Report",
            sections=[ReportSection(heading="Intro", body="body")],
            markdown="# Report\n\nbody",
        ),
    )

    restored = ResearchState.model_validate(state.model_dump())

    assert restored == state
    assert restored.kb is not None
    assert restored.kb.findings[0].chunk_id == chunk_id
    assert restored.stage is ResearchStage.DONE
