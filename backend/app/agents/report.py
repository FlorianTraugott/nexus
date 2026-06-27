"""Report-writer agent: the final stage of the research pipeline.

Turns the digest (state.summary) into a structured ResearchReport and records it
on the state, then advances to the terminal DONE stage. Mirrors the summariser:
a pure prompt builder asks the model for a single JSON object matching the
schema, and the reply is validated directly into ResearchReport (the model
supplies the rendered markdown alongside the structured sections).

Critical stage. A provider call failure propagates untouched so orchestration
can fail the run. Invalid model output is caught narrowly (only pydantic's
ValidationError) and re-raised as a specific MalformedReportError — never a bare
except, so a genuine bug does not hide behind "the model returned bad output".
A missing summary at this stage is an orchestration error and raises plainly.
"""

from pydantic import ValidationError

from app.agents.parsing import strip_code_fence
from app.schemas.research import (
    ResearchReport,
    ResearchStage,
    ResearchState,
    Summary,
)
from app.services.generation import GenerationProvider

# Keep the literal word "JSON" here: OpenAI's json_object mode requires it to
# appear in the prompt, so removing it would silently break structured output.
_SYSTEM_PROMPT = (
    "You are a research report writer. Using ONLY the provided summary, write a "
    "structured report on the topic. Respond with a single JSON object and "
    'nothing else, with exactly these fields: "title" (a short non-empty '
    'string), "sections" (a list of objects, each with non-empty "heading" and '
    '"body" strings), and "markdown" (the full report rendered as markdown, '
    "faithfully reflecting the title and sections). Do not invent facts beyond "
    "the summary."
)


class MalformedReportError(Exception):
    """The report-writer model returned output that is not a valid ResearchReport."""


def build_report_prompt(summary: Summary) -> tuple[str, str]:
    """Assemble the (system, user) prompts for a grounded structured report."""
    key_points = "\n".join(f"- {point}" for point in summary.key_points) or "(none)"
    user_prompt = f"Abstract:\n{summary.abstract}\n\nKey points:\n{key_points}"
    return _SYSTEM_PROMPT, user_prompt


async def run_report(
    state: ResearchState, generator: GenerationProvider
) -> ResearchState:
    """Generate a structured ResearchReport from the summary; advance to done."""
    if state.summary is None:
        # Orchestration guarantees summarise ran first; None here is a bug, not
        # a sparse-but-valid summary. Fail loudly rather than report nothing.
        raise ValueError("run_report requires state.summary; summarise must run first")

    system, prompt = build_report_prompt(state.summary)
    text = await generator.generate(system, prompt, json_mode=True)
    try:
        report = ResearchReport.model_validate_json(strip_code_fence(text))
    except ValidationError as exc:
        raise MalformedReportError(
            "report-writer model did not return a valid ResearchReport"
        ) from exc

    state.report = report
    state.stage = ResearchStage.DONE
    return state
