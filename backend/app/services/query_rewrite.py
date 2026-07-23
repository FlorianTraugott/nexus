"""Follow-up query rewriting: turn a conversational follow-up into a standalone
question for retrieval.

A follow-up like "what about the second one?" embeds to noise, so retrieval
fails. This service rewrites it into a self-contained question using the recent
conversation history, BEFORE retrieval. History is used ONLY to disambiguate the
question — it is never grounding context; answers still trace to retrieved
documents.

Best-effort: a failed rewrite degrades to worse retrieval (the original
question), never a failed request.
"""

from app.core.logging import get_logger
from app.services.generation import GenerationProvider, get_generation_provider

log = get_logger(__name__)

# Emphatic on the classic failure mode: the model must REWRITE, never ANSWER,
# and emit the bare question only.
_SYSTEM_PROMPT = (
    "You rewrite a user's latest question into a single standalone question for a "
    "document search engine. You do NOT answer it. Use the conversation history "
    'ONLY to resolve pronouns and elliptical references (for example "it", '
    '"that", "the second one") into an explicit, self-contained question that '
    "carries all the context needed to retrieve relevant documents on its own. "
    "Output ONLY the rewritten question as plain text — no answer, no explanation, "
    "no quotes, no preamble, no label. If the question is already standalone, "
    "return it unchanged."
)


def build_rewrite_prompt(
    question: str, history: list[tuple[str, str]]
) -> tuple[str, str]:
    """Assemble the (system, user) prompts for rewriting a follow-up.

    history is a list of (role, content) pairs in chronological order, decoupled
    from the ORM so this stays a pure, testable function.
    """
    dialogue = "\n".join(f"{role}: {content}" for role, content in history)
    user_prompt = (
        f"Conversation so far:\n{dialogue}\n\n"
        f"Latest question: {question}\n\n"
        "Standalone question:"
    )
    return _SYSTEM_PROMPT, user_prompt


async def rewrite_query(
    question: str,
    history: list[tuple[str, str]],
    generator: GenerationProvider | None = None,
) -> str:
    """Rewrite a follow-up into a standalone question; degrade to the original.

    Returns the question unchanged (no model call) when there is no history to
    disambiguate against.
    """
    if not history:
        return question

    generator = generator or get_generation_provider()
    system, prompt = build_rewrite_prompt(question, history)
    try:
        rewritten = await generator.generate(system, prompt)
    except Exception as exc:
        # Deliberately broad, unlike the narrow-catch convention (and exactly like
        # image captioning): query rewrite is strictly best-effort and the
        # generator has no single operational error class (OpenAI SDK, parsing).
        # ANY failure degrades to the original question — worse retrieval, never a
        # failed request.
        log.warning("query_rewrite_failed", error=str(exc))
        return question

    rewritten = rewritten.strip()
    if not rewritten:
        # Empty/parse failure is the other best-effort degrade path.
        log.warning("query_rewrite_empty")
        return question
    return rewritten
