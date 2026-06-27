"""Tests for the summariser agent: structured output, validation, grounding.

Offline: a FakeGenerationProvider returns canned JSON, so no model is called.
"""

import json
import uuid

import pytest
from tests.fakes import FakeGenerationProvider

from app.agents.summarise import (
    MalformedSummaryError,
    build_summary_prompt,
    run_summarise,
)
from app.schemas.research import (
    KBFinding,
    KBFindings,
    ResearchStage,
    ResearchState,
    Summary,
    WebSearchFindings,
    WebSearchHit,
)


def _web() -> WebSearchFindings:
    return WebSearchFindings(
        query="q",
        hits=[WebSearchHit(title="T", url="https://e.com", snippet="web snippet")],
    )


def _kb() -> KBFindings:
    return KBFindings(
        query="q",
        findings=[
            KBFinding(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                chunk_index=0,
                distance=0.1,
                content_preview="kb excerpt",
            )
        ],
    )


def _state(
    *, web: WebSearchFindings | None = None, kb: KBFindings | None = None
) -> ResearchState:
    return ResearchState(
        topic="quantum error correction",
        user_id=uuid.uuid4(),
        stage=ResearchStage.SUMMARISE,
        web=web,
        kb=kb,
    )


class BoomGenerator:
    """Generation provider that fails the call, to prove errors propagate."""

    async def generate(
        self, system: str, prompt: str, *, json_mode: bool = False
    ) -> str:
        raise RuntimeError("LLM down")


async def test_normal_path_populates_summary() -> None:
    answer = json.dumps({"key_points": ["p1", "p2"], "abstract": "An abstract."})
    generator = FakeGenerationProvider(answer=answer)

    result = await run_summarise(_state(web=_web(), kb=_kb()), generator)

    assert isinstance(result.summary, Summary)
    assert result.summary.key_points == ["p1", "p2"]
    assert result.summary.abstract == "An abstract."
    assert result.stage is ResearchStage.REPORT
    assert result.warnings == []
    assert result.error is None
    assert generator.json_modes == [True]  # structured output requested JSON mode


async def test_fenced_json_output_is_parsed() -> None:
    payload = json.dumps({"key_points": ["p"], "abstract": "An abstract."})
    generator = FakeGenerationProvider(answer=f"```json\n{payload}\n```")

    result = await run_summarise(_state(web=_web(), kb=_kb()), generator)

    assert isinstance(result.summary, Summary)
    assert result.summary.abstract == "An abstract."
    assert result.stage is ResearchStage.REPORT


@pytest.mark.parametrize(
    "answer",
    [
        "this is not json at all",
        json.dumps({"key_points": ["p"], "abstract": ""}),  # empty abstract: invalid
        json.dumps({"abstract": "missing key_points"}),
        "```json\nnot valid json\n```",  # invalid even after the fence is stripped
    ],
)
async def test_malformed_output_raises_specific_error(answer: str) -> None:
    state = _state(web=_web(), kb=_kb())

    with pytest.raises(MalformedSummaryError):
        await run_summarise(state, FakeGenerationProvider(answer=answer))

    # Not swallowed into a warning, and nothing half-written.
    assert state.summary is None
    assert state.warnings == []
    assert state.error is None


async def test_provider_failure_propagates() -> None:
    state = _state(web=_web(), kb=_kb())

    with pytest.raises(RuntimeError, match="LLM down"):
        await run_summarise(state, BoomGenerator())

    assert state.summary is None
    assert state.warnings == []


async def test_empty_context_still_calls_model_no_short_circuit() -> None:
    answer = json.dumps(
        {"key_points": [], "abstract": "No relevant information was found."}
    )
    generator = FakeGenerationProvider(answer=answer)
    state = _state(
        web=WebSearchFindings(query="q", hits=[]),
        kb=KBFindings(query="q", findings=[]),
    )

    result = await run_summarise(state, generator)

    assert generator.calls  # the model was called, not short-circuited
    assert result.summary is not None
    assert result.summary.abstract == "No relevant information was found."
    assert result.summary.key_points == []
    assert result.stage is ResearchStage.REPORT


def test_build_summary_prompt_includes_context_and_json_instruction() -> None:
    system, user = build_summary_prompt("my topic", _web(), _kb())

    assert "JSON" in system
    assert "key_points" in system and "abstract" in system
    assert "web snippet" in user
    assert "kb excerpt" in user
    assert "my topic" in user


def test_build_summary_prompt_handles_empty_context() -> None:
    system, user = build_summary_prompt("my topic", None, None)

    assert "no context" in user.lower()
    # Grounding instruction is present so the model still returns a valid Summary.
    assert "no relevant information" in system.lower()
