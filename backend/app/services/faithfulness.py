"""LLM-as-judge: score whether a generated answer is grounded in its context.

The judge is a different model family from the generator on purpose. A model
grading its own family's output shows self-preference bias -- it rewards its own
phrasing -- so the number it produces is not a measurement. The judge provider is
therefore built directly here rather than through get_generation_provider(),
which returns the single app-wide configured generator: routing through it would
mean swapping the whole app's generator to get a judge.

Nothing here is trustworthy until the judge is validated against the
hand-labelled calibration set (evals/run_faithfulness_calibration.py).
"""

from functools import lru_cache

from pydantic import BaseModel, ValidationError

from app.agents.parsing import strip_code_fence
from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.generation import (
    ClaudeGenerationProvider,
    GenerationProvider,
    OpenAIGenerationProvider,
)

log = get_logger(__name__)

# Keep the literal word "JSON" here: it is what makes prompt-for-JSON work, and
# we must not rely on the backend's structured-output mode -- the Gemini
# OpenAI-compat layer may ignore response_format, so the prompt carries the
# rules and strip_code_fence handles a fenced reply either way.
_JUDGE_SYSTEM = (
    "You are a strict grader. You are given CONTEXT passages and an ANSWER. "
    "Decompose the ANSWER into atomic factual claims -- each one a single "
    "self-contained assertion. For each claim, decide whether the CONTEXT "
    "supports it. Use ONLY the CONTEXT: a claim that is true in the real world "
    "but not present in the CONTEXT is NOT supported. "
    "Respond with a single JSON object and nothing else, with exactly one "
    'field: "claims", a list of objects each having "claim" (the atomic claim, '
    'quoted or closely paraphrased from the ANSWER), "supported" (true or '
    'false), and "reason" (one sentence naming the passage number that '
    "supports the claim, or stating what is missing from the CONTEXT). "
    "If the ANSWER makes no factual claims -- it is an abstention, a refusal, "
    'or a "not found in your documents" non-answer -- return an empty '
    '"claims" list.'
)


class ClaimJudgment(BaseModel):
    claim: str
    supported: bool
    reason: str


class _JudgeClaims(BaseModel):
    """Exactly what the judge returns.

    The judge decides claims; it does not compute the score. Arithmetic is not a
    thing to trust an LLM with, and computing it here makes a claims/score
    mismatch unrepresentable.
    """

    claims: list[ClaimJudgment]


class FaithfulnessVerdict(BaseModel):
    claims: list[ClaimJudgment]
    # supported / total -- or None when the answer made no factual claims (an
    # abstention). None rather than 1.0 so callers cannot average abstentions in
    # as perfect scores: a run that abstained on every question would otherwise
    # report perfect faithfulness. None makes forgetting a TypeError instead of
    # a plausible wrong number.
    score: float | None

    @property
    def is_abstention(self) -> bool:
        return self.score is None


class MalformedVerdictError(Exception):
    """The judge model returned output that is not a valid claim list.

    Carries the raw, pre-strip judge response so a diagnostic caller (the
    calibration runner) can see whether it was truncated, fenced, or genuinely
    malformed -- the whole point of catching this is to inspect what came back.
    """

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


def build_judge_prompt(answer: str, context: list[str]) -> tuple[str, str]:
    """Assemble the (system, user) prompts for a grounding judgment."""
    if context:
        passages = "\n\n".join(
            f"[{i}] {text}" for i, text in enumerate(context, start=1)
        )
    else:
        passages = "(no context passages were retrieved)"
    user_prompt = f"CONTEXT passages:\n{passages}\n\nANSWER:\n{answer}"
    return _JUDGE_SYSTEM, user_prompt


@lru_cache
def get_judge_provider() -> GenerationProvider:
    """Build the judge provider once and reuse it across calls."""
    settings = get_settings()
    if settings.JUDGE_PROVIDER == "gemini":
        if not settings.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY is not set; the faithfulness judge requires it"
            )
        # Gemini via its OpenAI-compatible endpoint: the same OpenAI client,
        # pointed at JUDGE_BASE_URL. A different model family from the generator.
        return OpenAIGenerationProvider(
            api_key=settings.GEMINI_API_KEY,
            model=settings.JUDGE_MODEL,
            max_tokens=settings.JUDGE_MAX_TOKENS,
            base_url=settings.JUDGE_BASE_URL,
        )
    if settings.JUDGE_PROVIDER == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set; the faithfulness judge requires it"
            )
        return ClaudeGenerationProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.JUDGE_MODEL,
            max_tokens=settings.JUDGE_MAX_TOKENS,
        )
    raise ValueError(f"Unknown judge provider: {settings.JUDGE_PROVIDER!r}")


async def _judge_once(
    judge: GenerationProvider, system: str, prompt: str
) -> FaithfulnessVerdict:
    """One generate-and-parse round; raises MalformedVerdictError on bad output."""
    # json_mode is advisory, not relied on: the Gemini OpenAI-compat layer may
    # ignore response_format, so the grounding rules live in the prompt and
    # strip_code_fence handles a fenced reply. (The Claude backend has no
    # json_object mode either, so the same fence-strip path covers it.)
    text = await judge.generate(system, prompt, json_mode=True)
    try:
        parsed = _JudgeClaims.model_validate_json(strip_code_fence(text))
    except ValidationError as exc:
        # Narrow on purpose: only invalid model output is wrapped, so bugs
        # elsewhere keep propagating as themselves.
        raise MalformedVerdictError(
            "judge model did not return a valid claim list", raw=text
        ) from exc

    if not parsed.claims:
        return FaithfulnessVerdict(claims=[], score=None)
    supported = sum(1 for c in parsed.claims if c.supported)
    return FaithfulnessVerdict(
        claims=parsed.claims, score=supported / len(parsed.claims)
    )


async def judge_faithfulness(
    answer: str,
    context: list[str],
    judge: GenerationProvider | None = None,
) -> FaithfulnessVerdict:
    """Judge whether `answer` is grounded in `context`; score = supported/total."""
    judge = judge or get_judge_provider()
    system, prompt = build_judge_prompt(answer, context)
    try:
        return await _judge_once(judge, system, prompt)
    except MalformedVerdictError as exc:
        # Gemini's OpenAI-compat layer doesn't strictly enforce response_format,
        # so prompt-for-JSON occasionally emits a malformed envelope (e.g. valid
        # JSON followed by a stray brace) non-deterministically -- the same entry
        # can pass on the next run. Retry exactly once. A second failure is a
        # real signal (a persistently broken judge), so it propagates with the
        # raw response attached rather than being papered over.
        log.warning("judge_output_malformed_retrying", raw_preview=exc.raw[:200])
        return await _judge_once(judge, system, prompt)
