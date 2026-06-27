"""Generation providers: turn a question + retrieved context into an answer.

Callers depend only on the GenerationProvider protocol, so the concrete
backend (OpenAI by default, Claude optional) can be swapped via config
without touching them. Prompt assembly lives in build_prompt — a pure
function, so the grounding rules can be tested without calling any model.
"""

from functools import lru_cache
from typing import Protocol

from anthropic import AsyncAnthropic
from anthropic.types import TextBlock
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.core.config import get_settings

_SYSTEM_PROMPT = (
    "You are a research assistant. Answer the user's question using ONLY the "
    "numbered context passages provided. If the answer is not contained in the "
    "context, say you don't have enough information to answer. Do not invent "
    "facts or rely on outside knowledge."
)


def build_prompt(question: str, contexts: list[str]) -> tuple[str, str]:
    """Assemble the (system, user) prompts for a grounded answer."""
    if contexts:
        passages = "\n\n".join(
            f"[{i}] {text}" for i, text in enumerate(contexts, start=1)
        )
    else:
        passages = "(no context passages were retrieved)"
    user_prompt = f"Context passages:\n{passages}\n\nQuestion: {question}"
    return _SYSTEM_PROMPT, user_prompt


class GenerationProvider(Protocol):
    """Produces a text answer from a system prompt and a user prompt."""

    async def generate(
        self, system: str, prompt: str, *, json_mode: bool = False
    ) -> str:
        """Return the model's answer; json_mode=True asks for a bare JSON object."""
        ...


class OpenAIGenerationProvider:
    """Generation backed by OpenAI chat completion models."""

    def __init__(self, api_key: str, model: str, max_tokens: int) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def generate(
        self, system: str, prompt: str, *, json_mode: bool = False
    ) -> str:
        # json_mode asks OpenAI for a single bare JSON object (no markdown fence),
        # which the structured agents validate directly. The non-structured
        # /query path omits response_format entirely, leaving it unchanged.
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        if json_mode:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=messages,
                response_format={"type": "json_object"},
            )
        else:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=messages,
            )
        return response.choices[0].message.content or ""


class ClaudeGenerationProvider:
    """Generation backed by Anthropic's Claude models."""

    def __init__(self, api_key: str, model: str, max_tokens: int) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def generate(
        self, system: str, prompt: str, *, json_mode: bool = False
    ) -> str:
        # Anthropic has no json_object response mode; the prompt already asks for
        # JSON and the structured agents strip any fenced output, so json_mode is
        # advisory here.
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in response.content if isinstance(block, TextBlock)
        )


@lru_cache
def get_generation_provider() -> GenerationProvider:
    """Build the configured provider once and reuse it across requests."""
    settings = get_settings()
    if settings.LLM_PROVIDER == "openai":
        return OpenAIGenerationProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.GENERATION_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    if settings.LLM_PROVIDER == "claude":
        return ClaudeGenerationProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    raise ValueError(f"Unknown LLM provider: {settings.LLM_PROVIDER!r}")
