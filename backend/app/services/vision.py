"""Vision providers: answer a question about one or more images.

A sibling to generation.py — same construction and call style — but the user
turn carries images alongside the text. Callers depend only on the
VisionProvider protocol so the backend can be swapped via config. The provider
base64-encodes image bytes itself and never reads from disk, so callers can
hand it bytes from any source (an extracted document figure, an upload).
"""

import base64
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionContentPartParam,
    ChatCompletionMessageParam,
)

from app.core.config import get_settings


@dataclass(frozen=True)
class VisionImage:
    """Raw image bytes plus their media type (e.g. "image/png")."""

    data: bytes
    media_type: str


class VisionProvider(Protocol):
    """Produces a text answer from a system prompt, a prompt, and images."""

    async def answer(
        self,
        system: str,
        prompt: str,
        images: list[VisionImage],
        *,
        detail: str = "auto",
    ) -> str:
        """Return the model's answer grounded in the supplied images."""
        ...


class OpenAIVisionProvider:
    """Vision answering backed by OpenAI chat completion models."""

    def __init__(self, api_key: str, model: str, max_tokens: int) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    async def answer(
        self,
        system: str,
        prompt: str,
        images: list[VisionImage],
        *,
        detail: str = "auto",
    ) -> str:
        # A vision call with no image is a programming error, not an empty
        # result — fail loud rather than silently sending a text-only request.
        if not images:
            raise ValueError("answer() requires at least one image")

        image_parts: list[ChatCompletionContentPartParam] = []
        for img in images:
            b64 = base64.b64encode(img.data).decode()
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img.media_type};base64,{b64}",
                        "detail": detail,  # type: ignore[typeddict-item]
                    },
                }
            )

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}, *image_parts],
            },
        ]
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=messages,
        )
        return response.choices[0].message.content or ""


@lru_cache
def get_vision_provider() -> VisionProvider:
    """Build the configured vision provider once and reuse it across requests."""
    settings = get_settings()
    if settings.LLM_PROVIDER == "openai":
        return OpenAIVisionProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.GENERATION_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    # Claude vision is deferred; only the OpenAI backend is wired up.
    raise NotImplementedError(
        f"Vision not supported for provider {settings.LLM_PROVIDER!r}"
    )
