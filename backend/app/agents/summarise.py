"""Summariser agent: the digest stage of the research pipeline.

Folds the web findings and the knowledge-base findings into one prompt, asks the
generation provider for a JSON object matching the Summary schema, validates it,
and records it on the state before advancing to the report stage.

This stage is critical, not best-effort. A provider call failure propagates
untouched so the orchestration layer can fail the run. Invalid model output is
an expected LLM failure mode, but without a valid summary there is nothing to
report, so it too fails the run — raised as a specific MalformedSummaryError and
caught narrowly (only pydantic's ValidationError), so a genuine bug never hides
behind "the model returned bad output".
"""

from pydantic import ValidationError

from app.schemas.research import (
    KBFindings,
    ResearchStage,
    ResearchState,
    Summary,
    WebSearchFindings,
)
from app.services.generation import GenerationProvider

_SYSTEM_PROMPT = (
    "You are a research summariser. Using ONLY the context provided, write a "
    "concise digest of what is known about the topic. Respond with a single "
    'JSON object and nothing else, with exactly these fields: "key_points" (a '
    'list of short strings) and "abstract" (a non-empty paragraph). If the '
    "context contains no relevant information, say so plainly in the abstract "
    '(for example, "No relevant information was found.") and use an empty '
    "key_points list. Do not invent facts beyond the context."
)


class MalformedSummaryError(Exception):
    """The summariser model returned output that is not a valid Summary."""


def build_summary_prompt(
    topic: str,
    web: WebSearchFindings | None,
    kb: KBFindings | None,
) -> tuple[str, str]:
    """Assemble the (system, user) prompts for a grounded structured summary."""
    web_hits = web.hits if web else []
    kb_findings = kb.findings if kb else []

    lines: list[str] = []
    if web_hits:
        lines.append("Web search results:")
        lines.extend(f"- {hit.title}: {hit.snippet}" for hit in web_hits)
    if kb_findings:
        lines.append("Knowledge base excerpts:")
        lines.extend(f"- {finding.content_preview}" for finding in kb_findings)
    context = "\n".join(lines) if lines else "(no context was gathered)"

    user_prompt = f"Topic: {topic}\n\nContext:\n{context}"
    return _SYSTEM_PROMPT, user_prompt


async def run_summarise(
    state: ResearchState, generator: GenerationProvider
) -> ResearchState:
    """Generate a structured Summary from web + KB findings; advance to report."""
    system, prompt = build_summary_prompt(state.topic, state.web, state.kb)
    text = await generator.generate(system, prompt)
    try:
        summary = Summary.model_validate_json(text)
    except ValidationError as exc:
        # Narrow on purpose: only invalid model output is wrapped, so bugs
        # elsewhere keep propagating as themselves.
        raise MalformedSummaryError(
            "summariser model did not return a valid Summary"
        ) from exc

    state.summary = summary
    state.stage = ResearchStage.REPORT
    return state
