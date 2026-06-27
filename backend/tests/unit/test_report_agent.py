"""Tests for the report-writer agent: structured output, validation, guard.

Offline: a FakeGenerationProvider returns canned JSON, so no model is called.
"""

import json
import uuid

import pytest
from tests.fakes import FakeGenerationProvider

from app.agents.report import (
    MalformedReportError,
    build_report_prompt,
    run_report,
)
from app.schemas.research import (
    ResearchReport,
    ResearchStage,
    ResearchState,
    Summary,
)

_VALID_REPORT = json.dumps(
    {
        "title": "Report Title",
        "sections": [{"heading": "Intro", "body": "Body text."}],
        "markdown": "# Report Title\n\n## Intro\n\nBody text.",
    }
)


def _summary(
    *, abstract: str = "An abstract.", key_points: list[str] | None = None
) -> Summary:
    return Summary(
        key_points=key_points if key_points is not None else ["k1", "k2"],
        abstract=abstract,
    )


def _state(*, summary: Summary | None) -> ResearchState:
    return ResearchState(
        topic="quantum error correction",
        user_id=uuid.uuid4(),
        stage=ResearchStage.REPORT,
        summary=summary,
    )


class BoomGenerator:
    """Generation provider that fails the call, to prove errors propagate."""

    async def generate(
        self, system: str, prompt: str, *, json_mode: bool = False
    ) -> str:
        raise RuntimeError("LLM down")


async def test_normal_path_populates_report() -> None:
    generator = FakeGenerationProvider(answer=_VALID_REPORT)

    result = await run_report(_state(summary=_summary()), generator)

    assert isinstance(result.report, ResearchReport)
    assert result.report.title == "Report Title"
    assert result.report.sections[0].heading == "Intro"
    assert result.report.markdown.startswith("# Report Title")
    assert result.stage is ResearchStage.DONE
    assert result.warnings == []
    assert result.error is None
    assert generator.json_modes == [True]  # structured output requested JSON mode


async def test_fenced_json_output_is_parsed() -> None:
    generator = FakeGenerationProvider(answer=f"```json\n{_VALID_REPORT}\n```")

    result = await run_report(_state(summary=_summary()), generator)

    assert isinstance(result.report, ResearchReport)
    assert result.report.title == "Report Title"
    assert result.stage is ResearchStage.DONE


@pytest.mark.parametrize(
    "answer",
    [
        "this is not json at all",
        json.dumps({"title": "", "sections": [], "markdown": "x"}),  # empty title
        json.dumps(
            {"title": "T", "sections": [{"heading": "H", "body": ""}], "markdown": "x"}
        ),  # empty section body
        json.dumps({"title": "T", "sections": []}),  # missing markdown
        "```json\nnot valid json\n```",  # invalid even after the fence is stripped
    ],
)
async def test_malformed_output_raises_specific_error(answer: str) -> None:
    state = _state(summary=_summary())

    with pytest.raises(MalformedReportError):
        await run_report(state, FakeGenerationProvider(answer=answer))

    assert state.report is None
    assert state.warnings == []
    assert state.error is None


async def test_provider_failure_propagates() -> None:
    state = _state(summary=_summary())

    with pytest.raises(RuntimeError, match="LLM down"):
        await run_report(state, BoomGenerator())

    assert state.report is None
    assert state.warnings == []


async def test_missing_summary_raises_guard() -> None:
    state = _state(summary=None)
    generator = FakeGenerationProvider(answer=_VALID_REPORT)

    with pytest.raises(ValueError, match="summary"):
        await run_report(state, generator)

    assert generator.calls == []  # guarded before any model call
    assert state.report is None


async def test_sparse_summary_still_calls_model_no_short_circuit() -> None:
    generator = FakeGenerationProvider(answer=_VALID_REPORT)
    sparse = _summary(abstract="No relevant information was found.", key_points=[])

    result = await run_report(_state(summary=sparse), generator)

    assert generator.calls  # the model was called, not short-circuited
    assert isinstance(result.report, ResearchReport)
    assert result.stage is ResearchStage.DONE


def test_build_report_prompt_includes_summary_and_json_instruction() -> None:
    system, user = build_report_prompt(
        _summary(abstract="MY ABSTRACT", key_points=["KP one"])
    )

    assert "JSON" in system
    assert all(field in system for field in ("title", "sections", "markdown"))
    assert "MY ABSTRACT" in user
    assert "KP one" in user
