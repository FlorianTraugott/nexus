"""Vision providers: answer a question about one or more images.

A sibling to generation.py — same construction and call style — but the user
turn carries images alongside the text. Callers depend only on the
VisionProvider protocol so the backend can be swapped via config. The provider
base64-encodes image bytes itself and never reads from disk, so callers can
hand it bytes from any source (an extracted document figure, an upload).
"""

import base64
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionContentPartParam,
    ChatCompletionMessageParam,
)
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.repositories.document import get_user_document_with_images


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


class DocumentNotFoundError(Exception):
    """The document does not exist or does not belong to the user."""

    def __init__(self, document_id: uuid.UUID) -> None:
        super().__init__(f"Document {document_id} not found")
        self.document_id = document_id


class NoDocumentImagesError(Exception):
    """The document exists but has no extracted images to ask about."""

    def __init__(self, document_id: uuid.UUID) -> None:
        super().__init__(f"Document {document_id} has no images")
        self.document_id = document_id


@dataclass(frozen=True)
class VisionAnswer:
    """A vision answer plus how many of the document's images were used."""

    answer: str
    images_used: int
    images_total: int


# Map on-disk suffix to the media type the provider needs. Unknown suffixes
# fail loud rather than being mislabelled as a fallback type.
_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_VISION_SYSTEM = (
    "You answer the user's question strictly from the provided document "
    "images. If the answer is not visible in the images, say you cannot "
    "determine it from the document."
)


async def answer_document_images(
    db: AsyncSession,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    *,
    detail: str = "auto",
) -> VisionAnswer:
    """Answer a question about one user's document using its extracted images.

    Loads the document (user-scoped, images eager-loaded), sends up to
    VISION_MAX_IMAGES pages to the vision provider in deterministic order, and
    reports how many images were used versus how many the document holds.
    """
    document = await get_user_document_with_images(db, document_id, user_id)
    if document is None:
        raise DocumentNotFoundError(document_id)

    images = sorted(document.images, key=lambda im: (im.page_number, im.image_index))
    if not images:
        raise NoDocumentImagesError(document_id)

    selected = images[: get_settings().VISION_MAX_IMAGES]
    vision_images = []
    for im in selected:
        path = Path(im.storage_path)
        suffix = path.suffix.lower()
        media_type = _MEDIA_TYPES.get(suffix)
        if media_type is None:
            raise ValueError(f"Unsupported image type {suffix!r} for {path}")
        vision_images.append(VisionImage(data=path.read_bytes(), media_type=media_type))

    provider = get_vision_provider()
    answer = await provider.answer(
        system=_VISION_SYSTEM, prompt=question, images=vision_images, detail=detail
    )
    return VisionAnswer(
        answer=answer, images_used=len(selected), images_total=len(images)
    )


_CAPTION_SYSTEM = (
    "You describe an image extracted from a document so that it can be found later by "
    "semantic search. Write a single dense paragraph, no preamble, no markdown.\n\n"
    "Transcribe every piece of text visible in the image: the title, axis labels, legend "
    "entries, and especially every data label and numeric value. State the chart or figure "
    "type. If the image shows data, restate the data points explicitly as label-value pairs. "
    "If the image is a logo, icon, decorative rule, or contains no meaningful information, "
    "reply with exactly: NO_CONTENT"
)
NO_CONTENT = "NO_CONTENT"


async def caption_image(path: Path) -> str | None:
    """Caption one image for search. Returns None if the image is junk or too small.

    Two cheap gates run before the billable vision call: an unsupported suffix and
    a below-threshold size both short-circuit to None. A NO_CONTENT or empty reply
    means the model judged the image not worth indexing.
    """
    suffix = path.suffix.lower()
    media_type = _MEDIA_TYPES.get(suffix)
    if media_type is None:
        return None

    min_px = get_settings().VISION_MIN_IMAGE_PX
    with Image.open(path) as im:
        width, height = im.size
    if width < min_px or height < min_px:
        return None

    image = VisionImage(data=path.read_bytes(), media_type=media_type)
    provider = get_vision_provider()
    # detail="high": chart data labels are small, and this read decides whether
    # the caption captures the numbers that make the image retrievable.
    result = await provider.answer(
        system=_CAPTION_SYSTEM,
        prompt="Describe this image for search.",
        images=[image],
        detail="high",
    )
    result = result.strip()
    if not result or result == NO_CONTENT:
        return None
    return result
